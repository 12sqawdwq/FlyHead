#!/usr/bin/env python3
"""SLAM / navigation compute service for the Xingtian (DIABLO) robot.

  robot/bridge.py --SSH stdio--> this server (compute host) <--SSH tunnel-- operator console

* Starts/stops the robot bridge over SSH (--robot-host) when a session is requested.
* Runs KISS-ICP LiDAR odometry and the voxel map in a separate compute process.
* Records every received frame to runs/<id>/raw.xt so sessions can be replayed.
* Runs navigation and forwards manual / autonomous commands with short leases.
* Serves /ws (control and status), /stream (pose), /camera, /diagnostics and downloads.
  The web UI itself is served on the operator PC by flyhead/monitor/preview.py.

Usage:
  python -m flyhead.server.app --robot-host ROBOT --robot-root /abs/path/on/robot --base MAP/map.ply --nav MAP
  python -m flyhead.server.app --replay runs/X/raw.xt [--speed 1]
scripts/start_server.sh holds the production command line (ROBOT is an SSH alias from ~/.ssh/config).
"""
import argparse
import asyncio
import copy
import json
import math
import os
import queue
import shlex
import struct
import threading
import time
import traceback
from collections import deque
from pathlib import Path

# Process-local budget, set before NumPy and inherited by spawned compute/bridge.
# Native KISS registration has its own explicit budget (slam.KISS_THREADS).
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import numpy as np
from aiohttp import web, WSMsgType

from flyhead.slam import lidar_slam as SL
from flyhead.slam.slam_process import SlamProcess
from flyhead.slam.recording import RawRecorder
from .remote_clock import RemoteClock
from flyhead.slam import rawlog
from flyhead.slam import reloc as RL
from flyhead.navigation import nav as NV
from .brain_link import BrainLink
from .arbiter import Arbiter

from flyhead import paths

HERE = Path(__file__).resolve().parent
ROOT = paths.REPO
RUNS = paths.runs_dir()
CMD_LEASE_S = 0.3
SPEED_HARD_MAX = 1.0            # m/s; no setting goes above this
# Operator speed ceiling, passed to the robot bridge as XT_MAX_V (the bridge clamps every command
# to it too).  0.30 unless the service is started with XT_MAX_V for speed exploration.
SPEED_LIMIT_MAX = max(0.05, min(SPEED_HARD_MAX, float(os.environ.get('XT_MAX_V', '0.30'))))
# Manual drive stays at the plain-navigation limit even when the ceiling is raised for Turbo (`fieldtest.sh up turbo`).
MANUAL_V_MAX = min(SPEED_LIMIT_MAX, NV.NORMAL_V_LIMIT)
MAX_TOUR_LAPS = 20
BAT_WARN, BAT_LOW = 25.0, 15.0     # % : warn / stop navigation, crouch, refuse new missions
IDLE_CROUCH_S = 60          # standing with no motion for this long -> crouch (motor heat)
BRAIN_IDLE_CROUCH_S = 300   # ... while the fly brain is driving
RECOVERY_TIMEOUT_S = 120.0
RECOVERY_CONFIRM_SAMPLES = 5


class Session:
    def __init__(self, app, replay=None, speed=1.0):
        self.app = app
        self.replay = replay
        self.speed = speed
        self.proc = None
        self.remote_clock = RemoteClock() if app.get('robot_host') else None
        self.replay_clock = None        # (first recorded wall time, replay start wall time) in replay
        # Physical motion needs both interlocks at startup: charging lock off and remote opt-in.
        self.chassis_disabled = (os.environ.get('XT_CHASSIS_DISABLED', '1') == '1'
                                 or os.environ.get('XT_REMOTE_MOTION_ENABLED', '0') != '1')
        self.run_dir = None
        self.raw = None
        self.lifecycle_lock = asyncio.Lock()
        self.finish_lock = threading.Lock()
        self.send_lock = asyncio.Lock()
        self.starting = False
        self.finish_error = None
        self.pipeline_fault = None
        self.command_sequence = 0
        self.command_send_ms = 0.0
        self.command_timeouts = 0
        self.slam = None
        self.last_slam = None
        self.slam_q = queue.Queue(maxsize=1)
        self.input_lock = threading.Lock()
        self.imu_samples = deque(maxlen=3000)
        self.cloud_batch = []
        self.queue_wait_s = 0.0
        self.imu_overruns = 0
        self.telemetry_q = queue.Queue(maxsize=256)
        self.telemetry_thread = None
        self.telemetry_dropped = 0
        self.telemetry_error = None
        self.last_control_tick = None
        self.slam_thread = None
        self.robot_status = {}
        self.events = []
        self.cmd = (0.0, 0.0)
        self.cmd_at = 0.0
        self.sent_zero = True
        self.rates = dict(clouds=0, imus=0, bytes=0)
        self.rate_view = {}
        self.started = None
        self.slam_dropped = 0
        self.reader_task = None
        self.last_imu = []
        self.jpeg = None          # latest camera frame (stamp, bytes), sent once
        self.nav = None
        self.idle_since = None
        self.clients_lost_at = None
        self.manual_client = None
        self.arb = Arbiter()               # exactly one motion owner at a time (flyhead/server/arbiter.py)
        self.posture_baseline = None      # robot posture_result 't' present when our request was sent
        self.nav_pending = 0              # nav tasks between ownership and start (async goal search)
        self.retrace_seen = False
        self.refusal_logged = {}
        self.arb_logged = 0               # last arbiter transition written to the event log
        self.brain = BrainLink(self)       # fly-brain mode (off unless XT_BRAIN_DIR)
        self.tour_laps = None           # {'total', 'done', 'active'} of a multi-lap tour
        self.drift_handled = None       # last map-correction drift event acted on
        self.bat_state = None
        self.reset_task = None
        self.runtime_reset = dict(state='idle', id=None, message='No reset requested yet')
        self.recovery = dict(state='idle', attempt=0)
        self.recovery_generation = 0
        self.localization_blocked = False
        self.recovery_deadline = None
        self.recovery_good_samples = 0
        self.recovery_last_frame = -1
        self.recovery_archives = queue.Queue(maxsize=1)
        self.recovery_archive_pending = 0
        self.failed_recovery_archives = []
        threading.Thread(target=self.recovery_archive_loop,
                         name='recovery-archive', daemon=True).start()

    def source_time(self, stamp):
        if self.replay_clock is not None and stamp is not None:
            # Replay: recorded times move onto the replay wall clock, so freshness gates
            # (navigation pose age, brain input age) see the data as it is being replayed.
            t0, w0 = self.replay_clock
            return w0 + (stamp - t0) / self.speed
        return self.remote_clock.source_time(stamp) if self.remote_clock is not None else stamp

    def wait_for_archive_idle(self):
        """Yield between save phases while recovery or motion needs the CPU."""
        while self.running:
            recovering = self.recovery['state'] in ('rebuilding', 'searching', 'confirming')
            navigating = self.nav is not None and self.nav.active
            moving = time.time() - self.cmd_at < CMD_LEASE_S and any(self.cmd)
            if not (recovering or navigating or moving):
                return
            time.sleep(0.2)

    def recovery_archive_loop(self):
        # Linux nice applies to this worker thread, not the control process.
        if hasattr(os, 'setpriority') and hasattr(threading, 'get_native_id'):
            try:
                os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 15)
            except OSError:
                pass
        while True:
            old, archive, summary = self.recovery_archives.get()
            try:
                self.wait_for_archive_idle()
                old.save(output=archive / 'before', wait_until_idle=self.wait_for_archive_idle,
                         frozen_summary=summary)
                (archive / 'archive_status.json').write_text(
                    json.dumps(dict(state='saved', completed_at=time.time())), encoding='utf-8')
                old.dispose()
            except Exception as error:
                # Retain the engine in memory for a session-end retry; never discard on error.
                self.failed_recovery_archives.append((old, archive, summary))
                self.app['loop'].call_soon_threadsafe(
                    self.event, 'Archiving the previous state failed; the snapshot is retained: %s' % error)
            finally:
                self.recovery_archive_pending -= 1
                self.recovery_archives.task_done()
                old = archive = summary = None

    @property
    def running(self):
        if self.replay:
            return self.reader_task is not None and not self.reader_task.done()
        return self.proc is not None and self.proc.returncode is None

    def end_owner(self, ended, why):
        """Side effects when the arbiter ends an owner: stop what that owner was running."""
        if ended == 'nav' and self.nav is not None:
            if self.nav.active or self.nav.tour_planning:
                self.nav.cancel(why)
            if self.tour_laps:
                self.tour_laps['active'] = False
        elif ended == 'brain' and self.brain.mode == 'drive':
            self.brain.mode = 'shadow'
        elif ended == 'manual':
            self.manual_client = None
        if ended:
            self.cmd, self.cmd_at = (0.0, 0.0), 0.0
        self.log_transitions()

    def log_transitions(self):
        """One event per ownership transition ('Control: idle -> brain (brain drive)'), in order."""
        for h in self.arb.history:
            if h['n'] > self.arb_logged:
                self.arb_logged = h['n']
                self.event('Control: %s -> %s (%s)' % (h['previous'], h['owner'], h['reason']))

    def refuse(self, client, why):
        """Report a refused control request, at most once per second per console and reason."""
        now = time.monotonic()
        if now - self.refusal_logged.get((client, why), -1e9) > 1.0:
            self.refusal_logged[(client, why)] = now
            self.event('Refused: %s' % why)

    def event(self, text, **kw):
        """Thread-safe: may be called from the SLAM / planner threads."""
        e = dict(t=time.time(), text=text, **kw)
        self.events = (self.events + [e])[-60:]
        self.record_telemetry(dict(type='event', **e))
        loop = self.app['loop']
        loop.call_soon_threadsafe(lambda: loop.create_task(broadcast(self.app, dict(type='event', **e))))

    def clear_inputs(self):
        self.cloud_batch = []
        with self.input_lock:
            self.imu_samples.clear()

    def record_telemetry(self, record):
        if self.telemetry_thread is None:
            return
        try:
            self.telemetry_q.put_nowait(record)
        except queue.Full:
            self.telemetry_dropped += 1

    def telemetry_loop(self, path, records):
        try:
            with path.open('a', encoding='utf-8', buffering=1) as stream:
                while True:
                    record = records.get()
                    if record is None:
                        return
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception as error:
            self.telemetry_error = repr(error)

    def record_control(self, started, command):
        nav = self.nav
        now = time.time()
        interval = None if self.last_control_tick is None else started - self.last_control_tick
        self.last_control_tick = started
        self.record_telemetry(dict(
            type='control', t=now, interval_s=interval,
            duration_s=time.monotonic() - started, requested_command=list(command),
            owner=self.arb.owner, controller=self.arb.controller_name, reflex=self.arb.reflex,
            pose=None if nav is None or nav.pose is None else [round(float(v), 3) for v in nav.pose[1:4]],
            queue_wait_s=self.queue_wait_s, dropped_clouds=self.slam_dropped,
            frame=None if self.slam is None else self.slam.frames,
            source_stamp=None if self.slam is None else self.slam.frame_stamp,
            proc_ms=None if self.slam is None else self.slam.proc_ms,
            stage_ms=None if self.slam is None else dict(self.slam.stage_ms),
            source_age_s=None if self.slam is None or self.source_time(self.slam.frame_stamp) is None
            else now - self.source_time(self.slam.frame_stamp),
            command_send_ms=self.command_send_ms,
            command_timeouts=self.command_timeouts,
            pipeline_fault=self.pipeline_fault,
            compute_rpc_ms=None if self.slam is None else self.slam.rpc_wall_ms,
            compute_worker_ms=None if self.slam is None else self.slam.worker_wall_ms,
            raw_recording=None if self.raw is None else self.raw.status(),
            pending_scans_dropped=None if self.slam is None else self.slam.pending_dropped,
            live_update_ms=None if nav is None else nav.live_update_ms,
            changes_update_ms=None if nav is None else nav.changes_update_ms,
            raycast_ms=None if nav is None else nav.raycast_ms,
            map_update_error=None if nav is None else nav.map_update_error,
            active=False if nav is None else nav.active,
            reason=None if nav is None else nav.reason,
            fitness=None if nav is None else nav.fitness,
            pose_age_s=None if nav is None or nav.pose is None else nav.pose_age(),
            pose_age_basis=None if nav is None else getattr(nav, 'pose_age_basis', None),
            receiver_age_s=None if nav is None or getattr(nav, 'input_received_at', None) is None
            else now - nav.input_received_at,
            live_age_s=None if nav is None or nav.control_layer is None else nav.layer_age(nav.control_layer),
            tour_route_mode='whole_route' if nav is not None and nav.leg == 'tour' else None,
            tour_progress_m=None if nav is None or nav.leg != 'tour' else nav.tour_progress_m,
            tour_length_m=None if nav is None or nav.leg != 'tour' or nav.tour_arc is None else float(nav.tour_arc[-1]),
            detour_count=None if nav is None else nav.detour_count,
            last_detour=None if nav is None else nav.last_detour,
            controller_mode=None if nav is None else nav.controller_mode,
            nav_decision=None if nav is None else nav.decision_snapshot(),
            robot_guard=self.guard_snapshot(),
        ))

    def guard_snapshot(self):
        """Robot-side protection state as reported by the chassis driver."""
        safety = (self.robot_status or {}).get('safety') or {}
        if not safety:
            return None
        nearest = safety.get('nearest_m')
        return dict(blocked=safety.get('blocked'), latched=safety.get('latched'),
                    present=safety.get('present'), fresh=safety.get('fresh'),
                    nearest_m=None if nearest is None else round(float(nearest), 3),
                    command_forward=safety.get('command_forward'),
                    command_turn=safety.get('command_turn'),
                    # Sector distances in the body frame: the host's stop / slow / detour
                    # chain decides with these; the chassis no longer enforces anything.
                    front_m=safety.get('front_m'), rear_m=safety.get('rear_m'),
                    left_m=safety.get('left_m'), right_m=safety.get('right_m'),
                    direction=[safety.get('direction_front'), safety.get('direction_rear'),
                               safety.get('direction_left'), safety.get('direction_right')])

    async def start(self, use_base=False):
        async with self.lifecycle_lock:
            if self.running or self.starting:
                return
            if self.finish_error is not None or (self.reader_task is not None and not self.reader_task.done()):
                self.event('The previous session is not archived yet; not overwriting it or starting a second one')
                return
            self.starting = True
            try:
                await self._start(use_base)
            except Exception as error:
                self.pipeline_fault = 'Session start failed: %s' % error
                self.event(self.pipeline_fault)
                await asyncio.get_running_loop().run_in_executor(None, self.finish)
            finally:
                self.starting = False

    def create_engine(self, base, masks=None, mode='crouch'):
        return SlamProcess(self.run_dir, base=base,
                           base_path=self.app.get('base_path') if base is not None else None,
                           masks=masks, mode=mode)

    async def _start(self, use_base=False):
        if self.remote_clock is not None:
            self.remote_clock = RemoteClock()
        self.pipeline_fault = None
        self.cmd, self.cmd_at = (0.0, 0.0), 0.0
        self.command_sequence = 0
        self.sent_zero = False
        self.recovery_generation += 1
        self.recovery = dict(state='idle', attempt=0)
        self.localization_blocked = False
        self.recovery_deadline = None
        base = self.app.get('base') if use_base else None
        if use_base and base is None:
            self.event('The base map is still loading; start again shortly (no fallback to a fresh mapping session)')
            return
        stamp = time.strftime('%Y%m%dT%H%M%S')
        self.run_dir = RUNS / (('replay_' if self.replay else 'live_') + stamp)
        self.run_dir.mkdir(parents=True)
        self.telemetry_q = queue.Queue(maxsize=256)
        self.telemetry_dropped = 0
        self.telemetry_error = None
        self.last_control_tick = None
        self.telemetry_thread = threading.Thread(
            target=self.telemetry_loop,
            args=(self.run_dir / 'navigation.jsonl', self.telemetry_q),
            name='navigation-recorder', daemon=True,
        )
        self.telemetry_thread.start()
        loop = asyncio.get_running_loop()
        if not self.replay:
            self.raw = await loop.run_in_executor(
                None, lambda: RawRecorder(self.run_dir / 'raw.xt',
                                          reserve_bytes=self.app.get('record_reserve_bytes', 64 * 1024 * 1024)))
        self.slam = await loop.run_in_executor(None, self.create_engine, base)
        if base is not None:
            (self.run_dir / 'BASE.json').write_text(json.dumps(dict(base=self.app['base_path']), ensure_ascii=False))
            self.event('Continuing on base map %s; relocalizing (if it takes long, drive a short distance slowly)'
                       % self.app['base_path'])
        self.nav = None
        if base is not None and self.app.get('nav_pkg'):
            self.nav = await loop.run_in_executor(
                None, lambda: NV.Navigator(self.app['nav_pkg'], self.run_dir / 'cloud_map',
                                           on_commit=self.on_cloud_commit))
            self.bind_navigation(self.slam, self.nav)
            self.event('Navigation map %s loaded; goals can be set once localized' % self.app['nav_pkg'])
        self.slam_q = queue.Queue(maxsize=1)
        self.clear_inputs()
        self.slam_dropped = 0
        self.imu_overruns = 0
        self.queue_wait_s = 0.0
        self.slam_thread = threading.Thread(target=self.slam_loop, name='slam-ipc', daemon=True)
        self.slam_thread.start()
        self.started = time.time()
        self.robot_status = {}
        if self.replay:
            self.reader_task = asyncio.get_event_loop().create_task(self.read_replay())
            self.event('Replaying %s' % self.replay)
        else:
            self.proc = await asyncio.create_subprocess_exec(
                *self.app['robot_cmd'], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=256 * 1024)
            self.reader_task = asyncio.get_event_loop().create_task(self.read_robot())
            asyncio.get_event_loop().create_task(self.read_stderr())
            self.event('Robot bridge connected; starting the LiDAR')
        if self.brain.enabled and self.brain.mode == 'off':
            # Shadow decodes and records but never commands motion, so the Stimulus panel and the brain
            # record are live from the start of every session; Roam and reflexes still need an operator.
            self.brain.set_mode('shadow')
            self.event('Brain mode: shadow (default at session start; decoded, never sent)')

    def bind_navigation(self, slam, nav):
        def on_frame(*values):
            if slam is not self.slam:
                return
            if self.localization_blocked:
                self.app['loop'].call_soon_threadsafe(
                    self.observe_recovery, slam, slam.frames, values[3]
                )
                return
            if nav is None:
                return
            nav.feed(*values, received_at=slam.input_received_at,
                     source_stamp=self.source_time(slam.frame_stamp),
                     processing_started_at=slam.processing_started_at)
            try:
                self.brain.on_scan(nav, values[2], values[1])
            except Exception as exc:          # brain mode must never break navigation
                self.brain.last['error'] = repr(exc)
            if slam.mode != nav.mode:
                slam.mode = nav.mode
                self.event('Posture change detected: %s (LiDAR %.2f m above the floor)'
                           % (nav.mode, nav.lidar_h or 0))
        slam.on_frame = on_frame

    async def request_recovery(self):
        if not self.running or self.replay or self.slam is None:
            self.event('Relocalization needs a running live session')
            return
        if self.slam.base is None and self.app.get('base') is None:
            self.event('The fixed base map is still loading; relocalization is not available yet')
            return
        if self.recovery['state'] in ('rebuilding', 'searching', 'confirming'):
            self.event('Relocalization is already in progress')
            return
        if self.recovery_archive_pending or self.recovery_archives.full() or self.failed_recovery_archives:
            self.event('Previous state archives are backlogged or failed; end the session first to keep the data')
            return
        self.recovery_generation += 1
        token = self.recovery_generation
        attempt = self.recovery['attempt'] + 1
        self.localization_blocked = True
        self.recovery_deadline = time.monotonic() + RECOVERY_TIMEOUT_S
        self.recovery_good_samples = 0
        self.recovery_last_frame = -1
        self.recovery = dict(state='rebuilding', attempt=attempt,
                             reason='Task paused, previous state frozen, localizer rebuilt now; full archive deferred',
                             good_samples=0, requested_at=time.time(),
                             raw_offset=self.raw.tell() if self.raw is not None else None)
        self.record_recovery()
        if self.nav is not None:
            self.nav.cancel('Relocalization: current task cancelled; dispatch it again afterwards')
        self.cmd = (0.0, 0.0)
        self.cmd_at = 0.0
        await self.send({'op': 'cmd', 'v': 0.0, 'w': 0.0})
        if token != self.recovery_generation:
            return
        self.last_imu = []
        self.clear_inputs()
        while True:
            try:
                queued = self.slam_q.get_nowait()
            except queue.Empty:
                break
            if queued is not None and queued[0] == 'cloud':
                self.slam_dropped += 1
        self.slam_q.put_nowait(('recover', token, attempt))
        self.event('Relocalization started: keep the robot in place while it re-matches the fixed base map; '
                   'no task resumes automatically')

    def record_recovery(self):
        if self.run_dir is None:
            return
        try:
            directory = self.run_dir / 'relocalization'
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(self.recovery, recorded_at=time.time()),
                                        ensure_ascii=False) + '\n')
        except OSError as error:
            self.event('Writing the relocalization log failed: %s' % error)

    def rebuild_localization(self, token, attempt):
        """Runs on the sole SLAM worker, never concurrently with frame processing."""
        if token != self.recovery_generation:
            return
        old = self.slam
        old_nav = self.nav
        new = None
        navigator = None
        try:
            old.close()
            if old_nav is not None:
                old_nav.close()
            archive = self.run_dir / 'relocalization' / ('attempt_%03d' % attempt)
            archive.mkdir(parents=True, exist_ok=True)
            (archive / 'archive_status.json').write_text(
                json.dumps(dict(state='deferred', requested_at=time.time())), encoding='utf-8')
            masks = old.recovery_masks()
            self.recovery_archive_pending += 1
            try:
                self.recovery_archives.put_nowait((old, archive, copy.deepcopy(old.summary())))
            except Exception:
                self.recovery_archive_pending -= 1
                raise
            (archive / 'request.json').write_text(json.dumps({
                'attempt': attempt, 'base': self.app['base_path'],
                'timeout_s': RECOVERY_TIMEOUT_S,
                'confirm_samples': RECOVERY_CONFIRM_SAMPLES,
                'minimum_fitness': NV.MIN_FITNESS,
                'resume_motion': False,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            if token != self.recovery_generation:
                return
            # Recover an accidental mapping-only session against the configured base.
            base = old.base if old.base is not None else self.app.get('base')
            if base is None:
                raise RuntimeError('Fixed base unavailable during localization recovery')
            new = self.create_engine(base, masks=masks, mode=old.mode)
            if self.app.get('nav_pkg'):
                navigator = NV.Navigator(self.app['nav_pkg'], archive / 'cloud_map',
                                         on_commit=self.on_cloud_commit)
                if old_nav is not None:
                    navigator.v_max = old_nav.v_max
                    navigator.w_max = old_nav.w_max
                    navigator.w_rotate = old_nav.w_rotate
                    navigator.turbo = old_nav.turbo
                    navigator.speed_gain = old_nav.speed_gain
                    navigator.changes.auto_submit = old_nav.changes.auto_submit
            self.bind_navigation(new, navigator)
            self.app['loop'].call_soon_threadsafe(
                self.install_recovery, token, new, navigator
            )
        except Exception as error:
            if new is not None:
                new.dispose()
            if navigator is not None:
                navigator.close()
            self.app['loop'].call_soon_threadsafe(self.fail_recovery, token, repr(error))

    def install_recovery(self, token, slam, nav):
        if token != self.recovery_generation or not self.running:
            slam.close()
            self.app['loop'].run_in_executor(None, slam.dispose)
            if nav is not None:
                nav.close()
            return
        # Drop frames queued during rebuilding; only newly arriving input is used.
        while True:
            try:
                queued = self.slam_q.get_nowait()
            except queue.Empty:
                break
            if queued is not None and queued[0] == 'cloud':
                self.slam_dropped += 1
        self.last_imu = []
        self.clear_inputs()
        self.slam, self.nav = slam, nav
        self.recovery.update(state='searching', reason='Collecting new scans for a global match against the base map',
                             input_cutover_at=time.time())
        self.record_recovery()
        self.event('Localizer rebuilt: the previous pose and path are discarded')

    def observe_recovery(self, slam, frame, fitness):
        if slam is not self.slam or self.recovery['state'] not in ('searching', 'confirming'):
            return
        # Every processed frame has fresh fitness; never count a repeated frame twice.
        if frame <= self.recovery_last_frame:
            return
        self.recovery_last_frame = frame
        good = fitness is not None and math.isfinite(fitness) and fitness >= NV.MIN_FITNESS
        self.recovery_good_samples = self.recovery_good_samples + 1 if good else 0
        self.recovery.update(state='confirming', good_samples=self.recovery_good_samples,
                             reason='Checking consecutive fitness of new poses against the base map')
        if self.recovery_good_samples >= RECOVERY_CONFIRM_SAMPLES:
            self.recovery_deadline = None
            self.localization_blocked = False
            self.recovery.update(state='ready', reason='Relocalized; set a new goal or tour')
            self.record_recovery()
            self.event('Relocalization complete; navigation stays stopped and the previous route is not resumed')

    def fail_recovery(self, token, reason):
        if token != self.recovery_generation:
            return
        self.recovery_generation += 1
        self.recovery_deadline = None
        self.localization_blocked = True
        self.recovery.update(state='failed', reason=reason)
        self.record_recovery()
        if self.slam is not None:
            self.slam.close()
        if self.nav is not None:
            self.nav.cancel('Relocalization did not complete')
        self.event('Relocalization did not complete: %s; motion stays stopped (retry or end the session)' % reason)

    async def check_drift(self):
        """Stop and relocalize when the map correction reports a large slip it may not apply.

        2026-10-08 23:09 (Turbo) the pose slipped 0.5 m; the correction found the 0.41 m fix but
        rejected it for its size and the robot drove on toward a mapped obstacle."""
        if self.slam is None or self.replay or self.recovery['state'] in ('rebuilding', 'searching', 'confirming'):
            return
        moving = (self.nav is not None and (self.nav.active or self.nav.tour_planning)) or any(self.cmd)
        if not moving:
            return
        try:
            summary = self.slam.summary()          # cached snapshot of the SLAM worker
        except Exception:
            return
        drift = ((summary or {}).get('map_correction') or {}).get('drift')
        if not drift or drift.get('event') == self.drift_handled:
            return
        self.drift_handled = drift.get('event')
        why = ('Localization slipped about %.2f m (map alignment %.2f -> %.2f); stopped, relocalizing'
               % (drift.get('step_m', 0.0), drift.get('fit_before', 0.0), drift.get('fit_after', 0.0)))
        if self.nav is not None:
            self.nav.cancel(why)
        if self.tour_laps:
            self.tour_laps['active'] = False
        self.cmd = (0.0, 0.0)
        self.cmd_at = 0.0
        await self.send({'op': 'cmd', 'v': 0, 'w': 0})
        self.event(why)
        await self.request_recovery()

    def poll_recovery(self):
        if self.recovery_deadline is not None and time.monotonic() >= self.recovery_deadline:
            self.fail_recovery(self.recovery_generation,
                               'no consecutive confident match within %.0f s' % RECOVERY_TIMEOUT_S)

    async def reset_runtime(self):
        """Recreate runtime state without deleting maps or restarting motion."""
        self.runtime_reset = dict(state='busy', id=str(time.time_ns()), message='Stopping the previous session safely')
        try:
            if self.replay or self.app.get('base') is None or not self.app.get('nav_pkg'):
                raise RuntimeError('a loaded base map and navigation package are required, and no replay')
            self.recovery_generation += 1
            self.recovery_deadline = None
            if self.nav is not None:
                self.nav.cancel('Operator reset the runtime configuration')
            self.cmd, self.cmd_at, self.manual_client = (0.0, 0.0), 0.0, None
            self.event('Runtime reset: previous task cancelled; maps, logs and safety thresholds are kept')
            if self.proc is not None and self.proc.returncode is None:
                await self.send({'op': 'cmd', 'v': 0, 'w': 0})
                status = self.robot_status
                if not status or not 0 <= time.time() - status.get('t', 0) < 2:
                    raise RuntimeError('chassis status is stale, a safe shutdown cannot be confirmed; '
                                       'check on site or restore status feedback first')
                if status.get('chassis_running'):
                    self.runtime_reset['message'] = 'Waiting for fresh crouch feedback before stopping the driver'
                    requested_at = time.time()
                    await self.send({'op': 'posture', 'stand': False})
                    deadline = time.monotonic() + 12
                    while True:
                        status = self.robot_status
                        body = status.get('body') or {}
                        age = time.time() - status.get('t', 0)
                        if (status.get('t', 0) > requested_at and 0 <= age < 1
                                and status.get('chassis_running')
                                and body.get('robot_mode') == 2
                                and 0 <= body.get('age', float('inf')) + age < 1):
                            break
                        if time.monotonic() >= deadline or self.proc.returncode is not None:
                            raise RuntimeError('no fresh crouch confirmation; reset aborted with zero velocity, '
                                               'check on site')
                        await self.send({'op': 'cmd', 'v': 0, 'w': 0})
                        await asyncio.sleep(0.2)
            self.runtime_reset['message'] = 'Stopping the previous acquisition and saving its records'
            await self.stop()
            if self.reader_task is not None and not self.reader_task.done():
                await asyncio.wait_for(asyncio.shield(self.reader_task), 15)
            if self.proc is not None and self.proc.returncode is None:
                raise RuntimeError('the previous bridge did not exit; no second acquisition was started')
            self.proc = None
            self.reader_task = None
            self.cmd, self.cmd_at, self.manual_client = (0.0, 0.0), 0.0, None
            self.sent_zero = True
            self.idle_since = None
            self.bat_state = None
            self.robot_status = {}
            self.jpeg = None
            self.rates = dict(clouds=0, imus=0, bytes=0)
            self.rate_view = {}
            self.runtime_reset['message'] = 'Restoring default navigation parameters and relocalizing on the base map'
            await self.start(use_base=True)
            if not self.running:
                raise RuntimeError('the new acquisition did not start; see the event log')
            self.nav.changes.auto_submit = True
            self.runtime_reset.update(
                state='ready', message='Defaults restored and acquisition restarted; once localized, '
                                       'start the chassis and a new task manually',
                defaults=dict(vmax=0.12, wmax=0.40, nvmax=NV.V_MAX, nwmax=NV.W_MAX),
            )
            self.event(self.runtime_reset['message'])
        except Exception as error:
            self.cmd, self.cmd_at = (0.0, 0.0), 0.0
            self.runtime_reset.update(state='failed', message='Reset did not complete: %s' % error)
            self.event(self.runtime_reset['message'])

    async def stop(self):
        self.brain.mode = 'off'
        self.arb.stop('session ending')
        async with self.lifecycle_lock:
            await self._stop()

    async def _stop(self):
        self.cmd, self.cmd_at = (0.0, 0.0), 0.0
        if self.nav is not None:
            self.nav.cancel('Session is ending')
        self.recovery_generation += 1
        self.recovery_deadline = None
        if self.localization_blocked:
            self.recovery.update(state='cancelled', reason='Session ended')
            self.record_recovery()
        if self.proc and self.proc.returncode is None:
            await self.send({'op': 'chassis', 'on': False})
            await self.send({'op': 'quit'})
            try:
                self.proc.stdin.close()
                await asyncio.wait_for(self.proc.wait(), 10)
            except (asyncio.TimeoutError, OSError):
                self.proc.kill()
        if self.reader_task and not self.reader_task.done():
            if self.replay:
                self.reader_task.cancel()
            else:
                # Drain every received frame through EOF before closing raw.xt.
                # The reader owns normal finalisation; do not race its last writes.
                await asyncio.shield(self.reader_task)
        await asyncio.get_event_loop().run_in_executor(None, self.finish)

    def finish(self):
        # read_robot and stop can both finish; only one may save/dispose engines.
        with self.finish_lock:
            try:
                self._finish()
                self.finish_error = None
            except Exception as error:
                self.finish_error = repr(error)
                self.event('Session archive incomplete; state retained and new sessions blocked: %s' % error)

    def _finish(self):
        # Drain the original sensor evidence even if compute later fails to save.
        if self.raw is not None:
            self.raw.close()
            self.raw = None
        if self.nav is not None:
            self.nav.cancel('Session ended')
            self.nav.close()
        if self.slam is not None:
            self.slam.close()
        if self.slam_thread:
            # Revoke queued compute, then let the sole RPC owner drain.
            while True:
                try:
                    self.slam_q.get_nowait()
                except queue.Empty:
                    break
            self.slam_q.put_nowait(None)
            self.slam_thread.join(timeout=185)
            if self.slam_thread.is_alive():
                raise TimeoutError('SLAM IPC worker did not stop; state retained')
            self.slam_thread = None
        # The bridge is stopped: flush deferred snapshots without competing with motion.
        self.recovery_archives.join()
        for old, archive, summary in list(self.failed_recovery_archives):
            old.save(output=archive / 'before', frozen_summary=summary)
            (archive / 'archive_status.json').write_text(
                json.dumps(dict(state='saved', completed_at=time.time())), encoding='utf-8')
            old.dispose()
            self.failed_recovery_archives.remove((old, archive, summary))
        if self.slam:
            self.slam.save()
            self.slam.dispose()
            self.event('Session ended; map saved to %s' % self.run_dir.name)
            self.last_slam, self.slam = self.slam, None
        if self.telemetry_thread is not None:
            try:
                self.telemetry_q.put(None, timeout=1.0)
                self.telemetry_thread.join(timeout=2.0)
            except queue.Full:
                self.telemetry_error = 'recorder did not drain at session end'
            self.telemetry_thread = None

    def on_cloud_commit(self, version, events):
        kinds = {}
        for e in events:
            kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        names = {'added': 'new obstacle', 'removed': 'obstacle removed', 'cleared': 'temporary obstacle cleared'}
        self.event('Shared map committed v%d: %s' % (
            version, ', '.join('%s %d' % (names.get(k, k), n) for k, n in kinds.items()) or 'no changes'))

    async def send(self, obj):
        packet = dict(obj)
        if self.chassis_disabled:
            operation = packet.get('op')
            if operation in ('posture', 'safety_reset') or (operation == 'chassis' and packet.get('on')):
                self.event('Charging lock: chassis and posture operations are disabled')
                return False
            if operation == 'cmd':
                packet.update(v=0.0, w=0.0)
        created = time.monotonic()
        packet.setdefault('deadline_mono', created + (CMD_LEASE_S if packet.get('op') == 'cmd' else 2.0))
        async with self.send_lock:
            proc = self.proc
            if proc is None or proc.returncode is not None or proc.stdin.is_closing():
                return False
            moving = packet.get('op') == 'cmd' and (packet.get('v') or packet.get('w'))
            pct = battery_pct(self)
            if moving and (self.pipeline_fault or time.monotonic() >= packet['deadline_mono']
                           or (pct is not None and pct < BAT_LOW)):
                packet.update(v=0.0, w=0.0)
            if moving and 'command-deadline-v1' not in self.robot_status.get('capabilities', []):
                packet.update(v=0.0, w=0.0)
            # Bound the transport backlog; never append another moving command to it.
            if proc.stdin.transport.get_write_buffer_size() > 8192:
                self.pipeline_fault = 'command transport backlog'
                return False
            if self.remote_clock is not None:
                if packet.get('op') == 'ping':
                    packet['clock_token'] = self.remote_clock.ping()
                elif packet.get('op') != 'quit':
                    translated = self.remote_clock.deadline(packet['deadline_mono'])
                    if translated is None:
                        if packet.get('op') != 'cmd':
                            self.event('Robot clock anchor unavailable; operation not executed, send it again shortly')
                            return False
                        packet.update(v=0.0, w=0.0)
                        translated = 0.0
                    packet['deadline_mono'] = translated
            self.command_sequence += 1
            packet['sequence'] = self.command_sequence
            try:
                proc.stdin.write((json.dumps(packet, allow_nan=False) + '\n').encode())
                await asyncio.wait_for(proc.stdin.drain(), 0.05)
                return True
            except asyncio.TimeoutError:
                self.command_timeouts += 1
                self.pipeline_fault = 'command transport drain timeout'
            except (ConnectionResetError, BrokenPipeError):
                self.pipeline_fault = 'command transport disconnected'
            finally:
                self.command_send_ms = (time.monotonic() - created) * 1000
        return False

    async def read_stderr(self):
        while self.proc and not self.proc.stderr.at_eof():
            line = await self.proc.stderr.readline()
            if line:
                self.event('ssh: ' + line.decode(errors='replace').strip())

    async def read_robot(self):
        r = self.proc.stdout
        try:
            while True:
                head = await r.readexactly(7)
                if head[:2] != b'XT':
                    raise ValueError('Invalid robot frame header')
                kind, n = struct.unpack('<BI', head[2:])
                if kind not in (1, 2, 3, 4) or n > 8 * 1024 * 1024:
                    raise ValueError('Invalid robot frame kind/length: %s/%s' % (kind, n))
                payload = await r.readexactly(n)
                received_at = time.time()
                if self.raw and not self.raw.write(struct.pack('<d', received_at) + head + payload):
                    self.pipeline_fault = self.raw.error or 'raw recorder unavailable'
                self.handle(kind, payload, received_at=received_at)
                # Buffered readexactly() need not yield; explicitly prevent a
                # sensor burst from monopolising the control/heartbeat loop.
                await asyncio.sleep(0)
        except asyncio.IncompleteReadError:
            pass
        except Exception as error:
            self.pipeline_fault = 'sensor transport: %r' % error
            if self.raw is not None:
                self.raw.error = self.pipeline_fault
            self.event(self.pipeline_fault)
            await self.send({'op': 'cmd', 'v': 0.0, 'w': 0.0})
            await self.send({'op': 'quit'})
            self.proc.stdin.close()
            # Reap the bridge without leaving its stdout transport paused/full.
            # The undecodable remainder is not presented as a complete recording.
            while await r.read(65536):
                await asyncio.sleep(0)
        await self.proc.wait()
        self.event('Robot bridge connection closed (exit %s)' % self.proc.returncode)
        await asyncio.get_running_loop().run_in_executor(None, self.finish)

    async def read_replay(self):
        t0 = w0 = None
        try:
            for wall, kind, payload in rawlog.read_records(self.replay):
                if t0 is None:
                    t0, w0 = wall, time.time()
                    self.replay_clock = (t0, w0)
                delay = (wall - t0) / self.speed - (time.time() - w0)
                if delay > 0:
                    await asyncio.sleep(delay)
                self.handle(kind, payload)
        finally:
            self.event('Replay finished')
            await asyncio.get_running_loop().run_in_executor(None, self.finish)

    def handle(self, kind, payload, received_at=None):
        self.rates['bytes'] += len(payload) + 7
        if self.remote_clock is not None and kind in (1, 2) and not self.remote_clock.ready():
            # Preserve raw bytes, but never turn unclocked input into fresh evidence.
            self.clear_inputs()
            return
        if kind == 1:
            stamp, n = struct.unpack('<dI', payload[:12])
            pts = np.frombuffer(payload, dtype='<f4', offset=12, count=n * 5).reshape(n, 5)
            self.rates['clouds'] += 1
            if self.slam is None or self.recovery['state'] in ('rebuilding', 'failed', 'cancelled'):
                return
            pts = pts[np.isfinite(pts).all(axis=1)]
            if not len(pts):
                return
            if self.cloud_batch and (stamp <= self.cloud_batch[-1][0]
                                     or stamp - self.cloud_batch[-1][0] > 0.5):
                self.slam_dropped += len(self.cloud_batch)
                self.cloud_batch = []
            self.cloud_batch.append((stamp, pts))
            first_stamp, first_points = self.cloud_batch[0]
            span = stamp + float(pts[:, 4].max()) - first_stamp - float(first_points[:, 4].min())
            window = SL.INIT_S if self.slam.frames == 0 else SL.ACC_S
            if span < window:
                return
            batch, self.cloud_batch = self.cloud_batch, []
            item = ('cloud', batch, time.time() if received_at is None else received_at, time.monotonic())
            try:
                self.slam_q.put_nowait(item)
            except queue.Full:
                try:
                    previous = self.slam_q.get_nowait()
                except queue.Empty:
                    previous = ('cloud', [], 0.0, 0.0)
                if previous is None or previous[0] == 'recover':
                    # Never replace a recovery request or shutdown sentinel.
                    self.slam_q.put_nowait(previous)
                    self.slam_dropped += len(batch)
                    return
                if previous[0] == 'cloud':
                    self.slam_dropped += len(previous[1])
                self.slam_q.put_nowait(item)
        elif kind == 2:
            v = struct.unpack('<d10f', payload)
            self.rates['imus'] += 1
            with self.input_lock:
                if len(self.imu_samples) == self.imu_samples.maxlen:
                    self.imu_overruns += 1
                self.imu_samples.append(v)
            # Wake a scan waiting for IMU coverage without competing with clouds
            # for queue capacity. A pending cloud already provides the wakeup.
            if (self.slam is not None and self.slam.pending
                    and self.recovery['state'] not in ('rebuilding', 'failed', 'cancelled')):
                try:
                    self.slam_q.put_nowait(('imu',))
                except queue.Full:
                    pass
        elif kind == 4:
            self.jpeg = payload
            self.rates['cam'] = self.rates.get('cam', 0) + 1
        elif kind == 3:
            obj = json.loads(payload)
            if obj.get('event') == 'clock' and self.remote_clock is not None:
                if self.remote_clock.accept(obj):
                    self.record_telemetry(dict(type='clock_anchor', **self.remote_clock.status()))
            elif obj.get('event') == 'status':
                if self.remote_clock is not None:
                    obj['robot_wall_t'] = obj.get('t')
                    obj['t'] = self.source_time(obj.get('t')) or 0.0
                self.robot_status = obj
            else:
                self.event('robot: ' + json.dumps(obj, ensure_ascii=False))

    def slam_loop(self):
        while True:
            item = self.slam_q.get()
            if item is None:
                return
            try:
                if item[0] == 'recover':
                    self.rebuild_localization(item[1], item[2])
                    continue
                if self.recovery['state'] in ('rebuilding', 'failed', 'cancelled'):
                    continue
                with self.input_lock:
                    samples = list(self.imu_samples)
                    self.imu_samples.clear()
                # A single batched RPC moves native registration, map insertion,
                # relocalisation and their GIL/locks into the compute process.
                if item[0] == 'cloud':
                    self.queue_wait_s = time.monotonic() - item[3]
                    self.slam.process_input(samples, item[1], item[2])
                else:
                    self.slam.process_input(samples, None, None)
            except Exception as exc:
                if self.slam is not None:
                    self.slam.last_error = repr(exc)
                self.pipeline_fault = 'SLAM compute failed: %r' % exc

    def status(self):
        s = self.slam or self.last_slam
        summary = s.summary() if s else None
        if summary is not None and self.localization_blocked:
            summary['attached'] = False
        return dict(type='status', running=self.running, replay=bool(self.replay),
                    recovery=dict(self.recovery), localization_blocked=self.localization_blocked,
                    runtime_reset=dict(self.runtime_reset), chassis_disabled=self.chassis_disabled,
                    base_path=self.app.get('base_path') if self.app.get('base') is not None else None,
                    run=self.run_dir.name if self.run_dir else None,
                    elapsed=time.time() - self.started if self.started and self.running else 0,
                    rates=self.rate_view, slam_dropped=self.slam_dropped, speed_limit_max=SPEED_LIMIT_MAX,
                    tour_laps=dict(self.tour_laps) if self.tour_laps else None, brain=self.brain.status(),
                    control=self.arb.status(),
                    pipeline=dict(queue_policy='latest_complete_scan', compute_isolation='spawn_process',
                                  fault=self.pipeline_fault, finish_error=self.finish_error,
                                  command_send_ms=self.command_send_ms, command_timeouts=self.command_timeouts,
                                  raw_recording=None if self.raw is None else self.raw.status(),
                                  queue_wait_s=self.queue_wait_s,
                                  imu_ring_evictions=self.imu_overruns,
                                  kiss_threads=SL.KISS_THREADS,
                                  telemetry_dropped=self.telemetry_dropped,
                                  telemetry_error=self.telemetry_error),
                    slam=summary, robot=self.robot_status,
                    cmd=list(self.cmd) if time.time() - self.cmd_at < CMD_LEASE_S else [0, 0])


def apply_nav_params(s, m):
    """Operator limits from a task or nav_params message: v (m/s), w (driving turn rate),
    wr (turn-in-place rate).  Absent values keep the current setting."""
    if s.nav is None:
        return
    if m.get('turbo') is not None and bool(m['turbo']) != s.nav.turbo:
        s.nav.set_turbo(bool(m['turbo']))
        s.event('Turbo %s: %s' % (('on', 'braking speed profile, measured-speed stop rule, up to %.2f m/s'
                                   % min(SPEED_LIMIT_MAX, NV.TURBO_V_LIMIT)) if s.nav.turbo
                                  else ('off', 'speed limit back to at most %.2f m/s' % NV.NORMAL_V_LIMIT)))
    if m.get('v') is not None:
        top = NV.TURBO_V_LIMIT if s.nav.turbo else NV.NORMAL_V_LIMIT
        s.nav.v_max = max(0.03, min(SPEED_LIMIT_MAX, top, float(m['v'])))
    s.nav.set_turn_limits(track=m.get('w'), rotate=m.get('wr'))


async def start_tour_lap(s):
    """Plan and start one lap of the whole-route tour (the lap counter lives in s.tour_laps)."""
    navigator = s.nav
    generation = s.recovery_generation
    revision = navigator.route_revision
    navigator.tour_planning = True
    laps = s.tour_laps or {}
    s.event('Planning tour lap %d of %d (approach and return included); no motion yet'
            % (laps.get('done', 0) + 1, laps.get('total', 1)))
    try:
        route, why = await asyncio.get_event_loop().run_in_executor(None, navigator.compute_loop)
    finally:
        navigator.tour_planning = False
    # Never discard a finished plan silently: a planned loop once vanished with no message.
    drops = []
    if s.localization_blocked:
        drops.append('waiting for relocalization')
    if generation != s.recovery_generation:
        drops.append('relocalized during planning')
    if s.nav is not navigator:
        drops.append('navigator was rebuilt')
    if revision != navigator.route_revision:
        drops.append('route was updated')
    if navigator.active:
        drops.append('another task is running')
    if not (s.slam and s.slam.attached):
        drops.append('SLAM is not localized')
    if laps and not laps.get('active'):
        drops.append('lap series was stopped')
    if drops:
        s.event('Tour route computed but not started: %s' % ', '.join(drops))
        if laps:
            laps['active'] = False
        return
    if route is None:
        s.event('Tour route planning failed: %s' % why)
        if laps:
            laps['active'] = False
        return
    ok, why = navigator.start_tour(route)
    li = navigator.loop_info
    s.event('Tour lap %d of %d: route %.1f m, loop %.1f m, speed limit %.2f m/s, turn %.2f / %.2f rad/s' % (
        laps.get('done', 0) + 1, laps.get('total', 1), li['route_length_m'], li['perimeter_m'], navigator.v_max,
        navigator.w_max, navigator.w_rotate) if ok else why)
    if not ok and laps:
        laps['active'] = False


async def next_tour_lap(s, navigator, pause_s=2.0):
    """Start the next lap after a short pause, unless anything changed meanwhile."""
    await asyncio.sleep(pause_s)
    laps = s.tour_laps
    if not laps or not laps.get('active') or s.nav is not navigator or navigator.active:
        return
    if battery_pct(s) is not None and battery_pct(s) < BAT_LOW:
        laps['active'] = False
        s.event('Battery %.0f%% is too low; lap series ended' % battery_pct(s))
        return
    await start_tour_lap(s)


async def broadcast(app, obj):
    data = json.dumps(obj, ensure_ascii=False)
    for ws in list(app['clients']):
        try:
            await asyncio.wait_for(ws.send_str(data), timeout=0.5)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError):
            app['clients'].discard(ws)
            asyncio.get_event_loop().create_task(ws.close())


async def broadcast_bin(app, data):
    for ws in list(app['display_clients']):
        try:
            await asyncio.wait_for(ws.send_bytes(data), timeout=0.5)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError):
            app['display_clients'].discard(ws)
            asyncio.get_event_loop().create_task(ws.close())


async def control_loop(app):
    """10 Hz: forward the freshest browser command, else a single zero + pings."""
    s = app['session']
    n = 0
    deadline = time.monotonic()
    while True:
        deadline += 0.1
        await asyncio.sleep(max(0.0, deadline - time.monotonic()))
        started = time.monotonic()
        if started - deadline > 0.1:
            deadline = started  # no burst of catch-up commands after a stall
        n += 1
        if not s.proc or s.proc.returncode is not None:
            if s.replay and s.running and s.brain.mode == 'shadow':
                # Replay has no robot link: evaluate shadow intents for the console and the log only.
                try:
                    _, _, rec = s.brain.command(time.time())
                except Exception as exc:
                    rec = dict(mode=s.brain.mode, withheld='brain link error %r' % exc)
                s.record_telemetry(dict(type='brain', t=time.time(), **rec))
            continue
        if s.raw is not None and s.raw.error:
            s.pipeline_fault = s.raw.error
        if s.pipeline_fault:
            s.cmd, s.cmd_at = (0.0, 0.0), 0.0
            if s.nav is not None:
                s.nav.cancel('Pipeline fault: %s' % s.pipeline_fault)
            s.end_owner(s.arb.halt('fault', 'pipeline fault: %s' % s.pipeline_fault), 'pipeline fault')
        else:
            s.arb.clear('fault')
        status_age = time.time() - s.robot_status.get('t', 0)
        status_fresh = 0 <= status_age < 2.0
        body = s.robot_status.get('body') or {}
        if (s.nav is not None and time.time() - s.robot_status.get('t', 0) < 3
                and body.get('age', 999) < 2 and body.get('robot_mode') in (2, 3)):
            s.nav.hardware_stand = body['robot_mode'] == 3
        if s.localization_blocked:
            s.cmd = (0.0, 0.0)
            s.cmd_at = 0.0
            if s.nav is not None:
                s.nav.cancel('Waiting for relocalization')
            s.end_owner(s.arb.halt('localization', 'waiting for relocalization'), 'waiting for relocalization')
        else:
            s.arb.clear('localization')
        if not s.localization_blocked and not s.pipeline_fault and s.nav is not None and s.nav.active:
            # The navigator has to know what the chassis guard is doing: the guard can stop
            # the robot on something the live route layer does not mark.
            s.nav.robot_guard = s.guard_snapshot()
            vw = s.nav.control(slam_ok=s.slam is not None and s.slam.attached,
                               chassis_ok=status_fresh and bool(s.robot_status.get('chassis_running')))
            if vw is not None:
                if s.arb.owner == 'nav':
                    s.arb.submit('nav', *vw)
                elif s.nav.active:
                    s.nav.cancel('Control owner is %s' % s.arb.owner)
                    s.event('Navigation stopped: control owner is %s' % s.arb.owner)
                s.cmd = vw
                s.cmd_at = time.time()
                if not s.nav.active:
                    s.event('Navigation ended: %s' % (s.nav.reason or {'arrived': 'goal reached'}.get(s.nav.state, s.nav.state)))
                    laps = s.tour_laps
                    if laps and laps.get('active'):
                        if s.nav.state == 'arrived':
                            laps['done'] += 1
                            if laps['done'] < laps['total']:
                                s.event('Lap %d of %d complete; planning the next lap' % (laps['done'], laps['total']))
                                asyncio.get_event_loop().create_task(next_tour_lap(s, s.nav))
                            else:
                                laps['active'] = False
                                s.event('All %d laps complete' % laps['total'])
                        else:
                            laps['active'] = False
                            s.event('Lap series ended after %d of %d laps' % (laps['done'], laps['total']))
        if (s.arb.owner == 'nav' and s.nav is not None and not s.nav.active and not s.nav.tour_planning
                and not s.nav_pending and not (s.tour_laps and s.tour_laps.get('active'))):
            s.arb.release('nav', 'navigation ended: %s' % (s.nav.reason or s.nav.state))
        if s.brain.mode != 'off':
            try:
                bv, bw, rec = s.brain.command(time.time())
            except Exception as exc:          # a brain fault must never stop the control loop
                bv, bw, rec = 0.0, 0.0, dict(mode=s.brain.mode, withheld='brain link error %r' % exc)
            if s.brain.mode == 'drive':
                if s.arb.owner != 'brain':
                    s.brain.mode = 'shadow'
                    s.event('Brain drive ended: control owner is %s (brain stays in shadow mode)' % s.arb.owner)
                else:
                    s.arb.submit('brain', bv, bw)
                    s.cmd = (bv, bw)
                    s.cmd_at = time.time() if (bv or bw) else 0.0
            elif s.brain.mode == 'reflex' and rec.get('takeover') and s.nav is not None and s.nav.active:
                # the planner's task holds while the brain freezes or escapes, then replans
                if not s.nav.reflex_engaged:
                    s.event('Fly-brain reflex: %s takes over from the planner' % rec.get('state'))
                    s.nav.add_keepout(s.brain.threat_xy)     # later plans give the threat a wide berth
                s.nav.reflex_hold(rec.get('state'))
                s.arb.submit('nav', bv, bw, reflex=True)
                s.cmd = (bv, bw)
                s.cmd_at = time.time()
                rec['planner_held'] = True
            s.record_telemetry(dict(type='brain', t=time.time(), **rec))
        ended = s.arb.expire()
        if ended:
            s.end_owner(ended, s.arb.reason)
        s.log_transitions()
        if s.arb.owner == 'posture':
            pr = s.robot_status.get('posture_result') or {}
            if pr.get('ok') in (True, False) and pr.get('t') != s.posture_baseline:
                s.arb.release('posture', 'posture %s' % pr.get('state'))
        if s.arb.owner == 'retrace':
            lr = s.robot_status.get('link_return') or {}
            if lr.get('active'):
                s.retrace_seen = True
            elif s.retrace_seen:
                s.retrace_seen = False
                s.arb.release('retrace', 'return along the path finished')
        now = time.time()
        await battery_policy(s)
        # Network observations do not gate a locally running autonomous task.
        # Local command leases, localization, battery and driver guards still apply.
        moving = (now - s.cmd_at < CMD_LEASE_S and (s.cmd[0] or s.cmd[1])) or (
            s.nav is not None and s.nav.active and s.nav.state != 'waiting')
        standing = s.nav is not None and (s.nav.hardware_stand is True or s.nav.mode == 'stand')
        if moving or not standing or not s.robot_status.get('chassis_running'):
            s.idle_since = None
        else:
            s.idle_since = s.idle_since or now
            # brain drive waits for stimuli while standing still: allow it longer before crouching
            if now - s.idle_since > (BRAIN_IDLE_CROUCH_S if s.brain.mode == 'drive' else IDLE_CROUCH_S):
                s.idle_since = None
                if s.nav.active and s.nav.leg != 'tour':
                    # A point-to-point task cannot survive a posture change.
                    s.nav.cancel('Waited more than %d s; crouching for safety, dispatch the task again later'
                                 % IDLE_CROUCH_S)
                    s.cmd, s.cmd_at = (0.0, 0.0), 0.0
                # A whole-route tour keeps running: its route was planned for a height
                # at least as tall as the crouched robot, and the planner rebuilds the
                # obstacle layer for the new posture.  Cancelling the tour here was a
                # verified way to end a lap that was only waiting for an obstacle
                # (live_20261006T212844 stopped at 1.05 m of 248 m for this reason).
                if s.arb.owner == 'brain':
                    s.end_owner(s.arb.stop('standing idle; crouching'), 'standing idle')
                if s.arb.owner == 'idle' and s.arb.request('posture', reason='idle crouch')[0]:
                    s.posture_baseline = (s.robot_status.get('posture_result') or {}).get('t')
                await s.send({'op': 'posture', 'stand': False})
                s.event('Standing idle too long; crouching automatically (motor heat)')
        v, w = s.arb.command(CMD_LEASE_S)      # only the control owner's command, while its lease holds
        if (not status_fresh or s.pipeline_fault or time.monotonic() - started >= CMD_LEASE_S):
            v, w = 0.0, 0.0
        if v or w:
            remaining = max(0.0, CMD_LEASE_S - (time.monotonic() - s.arb.cmd_at))
            deadline_mono = min(started + CMD_LEASE_S, time.monotonic() + remaining,
                                time.monotonic() + max(0.0, 2.0 - (time.time() - s.robot_status.get('t', 0))))
            if s.nav is not None and s.nav.active:
                deadline_mono = min(
                    deadline_mono,
                    time.monotonic() + max(0.0, NV.POSE_STALE_S - s.nav.pose_age()),
                    time.monotonic() + max(0.0, NV.POSE_STALE_S - s.nav.layer_age(s.nav.control_layer)),
                )
            await s.send({'op': 'cmd', 'v': v, 'w': w, 'deadline_mono': deadline_mono})
            s.sent_zero = False
        elif not s.sent_zero:
            await s.send({'op': 'cmd', 'v': 0, 'w': 0})
            s.sent_zero = True
        s.record_control(started, (v, w))


async def heartbeat_loop(app):
    """Transport liveness is independent of navigation work; never renew motion.

    Bridge command deadlines still stop motion at 0.3 s. A control coroutine
    failure latches a fault; heartbeat does not pretend that navigation is healthy.
    """
    session = app['session']
    while True:
        await asyncio.sleep(0.25)
        if session.running and not session.replay:
            if app['background_errors'].get('control'):
                session.pipeline_fault = 'control task failed'
            if session.pipeline_fault:
                await session.send({'op': 'cmd', 'v': 0.0, 'w': 0.0})
            await session.send({'op': 'ping'})


async def publish_loop(app):
    """Refresh the 1 s rate counters and push the body pose (~10 Hz) to /stream."""
    s = app['session']
    last_rate = time.time()
    while True:
        await asyncio.sleep(0.1)
        now = time.time()
        if now - last_rate >= 1.0:
            dt = now - last_rate
            s.rate_view = {key: v / dt for key, v in s.rates.items()}
            s.rates = dict(clouds=0, imus=0, bytes=0)
            last_rate = now
        if not s.slam or not (app['clients'] or app['display_clients']):
            continue
        if s.slam.take_reset():
            await broadcast_bin(app, b'\x06')
            if s.slam.attached and s.slam.base is not None:
                s.event('Relocalized; mapping continues in the base map frame')
        pose = s.slam.take_pose()
        if pose is not None:
            await broadcast_bin(app, b'\x01' + pose.astype('<f4').tobytes())


def battery_pct(s):
    b = (s.robot_status or {}).get('battery') or {}
    status_age = time.time() - (s.robot_status or {}).get('t', 0)
    return b.get('pct') if 0 <= status_age < 5 and 0 <= b.get('age', 99) + status_age < 5 else None


async def battery_policy(s):
    pct = battery_pct(s)
    if pct is None:
        return
    state = 'low' if pct < BAT_LOW else 'warn' if pct < BAT_WARN else 'ok'
    if state == 'low':
        s.end_owner(s.arb.halt('battery', 'battery %.0f%% (below %.0f%%)' % (pct, BAT_LOW)), 'battery low')
    else:
        s.arb.clear('battery')
    if state != s.bat_state:
        s.bat_state = state
        if state == 'warn':
            s.event('Battery %.0f%%, below %.0f%%: return to the charger soon' % (pct, BAT_WARN))
        elif state == 'low':
            s.event('Battery %.0f%%, below %.0f%%: navigation stopped%s' % (
                pct, BAT_LOW, ' and crouching' if s.nav is not None and s.nav.mode == 'stand' else ''))
    if state == 'low':
        s.cmd, s.cmd_at, s.manual_client = (0.0, 0.0), 0.0, None
        if s.nav is not None and s.nav.active:
            s.nav.cancel('Battery too low (%.0f%%)' % pct)
        if (s.nav is not None and (s.nav.mode == 'stand' or s.nav.hardware_stand is True)
                and not getattr(s, 'bat_crouched', False)):
            s.bat_crouched = True
            await s.send({'op': 'posture', 'stand': False})


async def chassis_retry(s, generation):
    """Retry a driver start only while its original session request is current."""
    await asyncio.sleep(4.0)
    if s.localization_blocked or generation != s.recovery_generation:
        return
    r = s.robot_status
    if s.proc and not r.get('chassis_running') and r.get('chassis_exit') == 0:
        s.event('Chassis driver exited 0: control authority was not yet released; retrying once in 3 s')
        await asyncio.sleep(3.0)
        if not s.localization_blocked and generation == s.recovery_generation:
            await s.send({'op': 'chassis', 'on': True})


async def display_handler(request):
    """Pose stream: b'\x06' on a frame reset, b'\x01' + 4x4 float32 body pose."""
    app = request.app
    ws = web.WebSocketResponse(heartbeat=5, max_msg_size=1024)
    await ws.prepare(request)
    try:
        await ws.send_bytes(b'\x06')
        app['display_clients'].add(ws)
        async for message in ws:
            pass
    finally:
        app['display_clients'].discard(ws)
    return ws


async def camera_handler(request):
    """A subscription does not start the camera or a robot session."""
    ws = web.WebSocketResponse(heartbeat=5, max_msg_size=1024)
    await ws.prepare(request)
    request.app['camera_clients'].add(ws)
    try:
        async for message in ws:
            pass
    finally:
        request.app['camera_clients'].discard(ws)
    return ws


async def status_loop(app):
    """Status traffic is independent of map and camera backpressure."""
    session = app['session']
    while True:
        await asyncio.sleep(0.3)
        session.poll_recovery()
        await session.check_drift()
        if app['clients']:
            await broadcast(app, session.status())
            if session.nav is not None:
                await broadcast(app, session.nav.status())


async def camera_loop(app):
    """Send only the latest JPEG; close stalled subscribers instead of queuing."""
    session = app['session']

    async def send_frame(ws, data):
        try:
            await asyncio.wait_for(ws.send_bytes(data), timeout=0.5)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError):
            app['camera_clients'].discard(ws)
            await ws.close()

    while True:
        await asyncio.sleep(0.1)
        jpeg, session.jpeg = session.jpeg, None
        if jpeg is None or not app['camera_clients']:
            continue
        await asyncio.gather(*[
            send_frame(ws, b'\x05' + jpeg)
            for ws in list(app['camera_clients'])
        ])


async def ws_handler(request):
    app = request.app
    s = app['session']
    ws = web.WebSocketResponse(heartbeat=5, max_msg_size=1 << 20)
    await ws.prepare(request)
    app['clients'].add(ws)
    s.clients_lost_at = None
    app['client_seq'] = app.get('client_seq', 0) + 1
    cid = id(ws)
    cname = 'console %d (%s)' % (app['client_seq'], request.remote or 'local')
    await ws.send_str(json.dumps(
        dict(type='hello', events=s.events, channels=['/stream', '/camera'], you=cname,
             capabilities=['ping', 'relocalize', 'reset-runtime']),
        ensure_ascii=False,
    ))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except ValueError:
                continue
            t = m.get('t')
            if s.reset_task is not None and not s.reset_task.done() and t not in ('ping', 'stop_motion'):
                s.event('Runtime reset in progress; other controls and repeated resets are refused '
                        '(emergency stop still works)')
                continue
            requests_motion = t in ('cmd', 'tour', 'explore', 'go_home', 'posture', 'safety_reset')
            requests_motion = requests_motion or (t in ('nav', 'chassis') and m.get('on'))
            if s.chassis_disabled and requests_motion:
                s.event('Charging lock: only sensors, localization and host functions are allowed; '
                        'chassis operations are disabled')
                continue
            if s.pipeline_fault and requests_motion:
                s.event('A pipeline fault locks motion; end the session and resolve it: %s' % s.pipeline_fault)
                continue
            if s.localization_blocked and requests_motion:
                s.event('Relocalization has not completed, so motion cannot start; stop, retry relocalization '
                        'or end the session')
                continue
            if t in ('goal', 'nav_params', 'cloud_submit', 'auto_submit', 'safety_reset'):
                ok, why = s.arb.allowed(cid)
                if not ok:
                    s.refuse(cid, why)
                    continue
            if t == 'take_control':
                previous, ended = s.arb.take_control(cid, cname)
                s.end_owner(ended, 'control taken by %s' % cname)
                s.event('Control taken by %s%s' % (cname, (' from %s' % previous) if previous else ''))
                continue
            if t == 'reset_runtime':
                if m.get('confirm') is not True:
                    s.event('Reset needs explicit confirmation: it clears the old task and relocalizes, '
                            'without starting motion')
                else:
                    s.reset_task = asyncio.get_event_loop().create_task(s.reset_runtime())
            elif t == 'relocalize':
                if m.get('x') is not None and m.get('y') is not None:
                    # Operator pose hint for a session still searching on the base map.
                    if not s.slam or s.slam.base is None or s.slam.attached:
                        s.event('A pose hint only helps a session still searching on the base map')
                    else:
                        yaw = None if m.get('yaw') is None else float(m['yaw'])
                        await asyncio.get_event_loop().run_in_executor(
                            None, s.slam.set_reloc_hint, float(m['x']), float(m['y']), yaw)
                        s.event('Relocalization pose hint set: (%.2f, %.2f)%s; a match within 1 m and '
                                'fitness 0.8 is accepted' % (float(m['x']), float(m['y']),
                                '' if yaw is None else ', yaw %.0f deg' % math.degrees(yaw)))
                else:
                    await s.request_recovery()
            elif t == 'ping':
                await ws.send_json(dict(type='pong', id=m.get('id')))
            elif t == 'cmd':
                v, w = float(m.get('v', 0)), float(m.get('w', 0))
                if not (math.isfinite(v) and math.isfinite(w)):
                    continue
                if v or w or s.arb.owner == 'manual':
                    ok, why, ended = s.arb.request('manual', cid, cname, 'manual drive')
                    if not ok:
                        s.refuse(cid, why)
                        continue
                    s.end_owner(ended, 'manual takeover by %s' % cname)
                    s.manual_client = ws if v or w else None
                    v, w = max(-MANUAL_V_MAX, min(MANUAL_V_MAX, v)), max(-1., min(1., w))
                    s.arb.submit('manual', v, w)
                    s.cmd, s.cmd_at = (v, w), time.time()
            elif t == 'stop_motion':
                s.end_owner(s.arb.stop('emergency stop by %s' % cname), 'emergency stop')
                if s.brain.mode == 'drive':
                    s.brain.mode = 'shadow'
                    s.event('Brain drive ended: emergency stop (brain stays in shadow mode)')
                if s.nav is not None:
                    s.nav.cancel('Emergency stop')
                    s.event('Navigation stopped: emergency stop')
                s.cmd = (0.0, 0.0)
                s.cmd_at = 0.0
                await s.send({'op': 'cmd', 'v': 0, 'w': 0})
            elif t == 'session':
                if m.get('on'):
                    await s.start(use_base=bool(m.get('base')))
                else:
                    await s.stop()
            elif t == 'chassis':
                if not s.proc:
                    s.event('Start a LiDAR session first')
                else:
                    s.cmd = (0.0, 0.0)
                    if not m.get('on'):
                        s.end_owner(s.arb.stop('chassis stopped by %s' % cname), 'chassis stopped')
                    await s.send({'op': 'chassis', 'on': bool(m.get('on'))})
                    if m.get('on'):
                        asyncio.get_event_loop().create_task(chassis_retry(s, s.recovery_generation))
            elif t == 'camera':
                await s.send({'op': 'camera', 'on': bool(m.get('on'))})
            elif t == 'goal':
                if s.nav is None:
                    s.event('Navigation is not enabled (start a base-map continuation session with a '
                            'navigation package)')
                else:
                    s.nav.set_goal(float(m['x']), float(m['y']))
                    s.event('Navigation goal (%.2f, %.2f); planning' % (float(m['x']), float(m['y'])))
            elif t == 'nav':
                if s.nav is None:
                    s.event('Navigation is not enabled')
                elif m.get('on'):
                    if not s.robot_status.get('chassis_running'):
                        s.event('Start the chassis first')
                    elif not (s.slam and s.slam.attached):
                        s.event('Not localized on the base map yet; navigation cannot start')
                    else:
                        ok, why, ended = s.arb.request('nav', cid, cname, 'navigation')
                        if not ok:
                            s.refuse(cid, why)
                        else:
                            s.end_owner(ended, 'navigation started')
                            ok, why = s.nav.start()
                            if not ok:
                                s.arb.release('nav', 'navigation did not start')
                            s.event('Autonomous navigation started' if ok else why)
                else:
                    s.arb.release('nav', 'stopped by %s' % cname)
                    s.nav.cancel('Stopped by the operator')
                    if s.tour_laps:
                        s.tour_laps['active'] = False
                    s.cmd = (0.0, 0.0)
                    s.cmd_at = 0.0
                    await s.send({'op': 'cmd', 'v': 0, 'w': 0})
                    s.event('Navigation stopped')
            elif t == 'tour':
                if battery_pct(s) is not None and battery_pct(s) < BAT_LOW:
                    s.event('Battery %.0f%% is too low; new navigation tasks are refused' % battery_pct(s))
                    continue
                # The chassis status is sampled, not live: a wireless gap made this refuse a
                # fully planned 249.6 m loop (live_20261007T001558).  The navigator now holds
                # and resumes while the chassis state is unavailable, so only the real
                # prerequisites remain: an idle navigator and a localised SLAM.
                if s.nav is None or s.nav.active or s.nav.tour_planning or not (s.slam and s.slam.attached):
                    s.event('Cannot start a tour: navigation must be idle and localized')
                else:
                    ok, why, ended = s.arb.request('nav', cid, cname, 'tour')
                    if not ok:
                        s.refuse(cid, why)
                        continue
                    s.end_owner(ended, 'tour started')
                    apply_nav_params(s, m)
                    s.tour_laps = dict(total=int(max(1, min(MAX_TOUR_LAPS, int(m.get('laps', 1))))), done=0, active=True)
                    await start_tour_lap(s)
            elif t in ('explore', 'go_home'):
                if battery_pct(s) is not None and battery_pct(s) < BAT_LOW:
                    s.event('Battery %.0f%% is too low; new navigation tasks are refused' % battery_pct(s))
                    continue
                if s.nav is None:
                    s.event('Navigation is not enabled')
                elif s.nav.active:
                    s.event('Navigation is already active')
                elif not s.robot_status.get('chassis_running'):
                    s.event('Start the chassis first')
                elif not (s.slam and s.slam.attached):
                    s.event('Not localized on the base map yet')
                else:
                    ok, why, ended = s.arb.request('nav', cid, cname, t.replace('_', ' '))
                    if not ok:
                        s.refuse(cid, why)
                        continue
                    s.end_owner(ended, '%s started' % t)
                    apply_nav_params(s, m)
                    if t == 'go_home':
                        ok, why = s.nav.go_home()
                        if not ok:
                            s.arb.release('nav', 'return home did not start')
                        s.event(('Returning to the start point %s' % (s.nav.home,)) if ok else why)
                    else:
                        navigator = s.nav
                        generation = s.recovery_generation
                        s.nav_pending += 1
                        try:
                            goal, why = await asyncio.get_event_loop().run_in_executor(None, navigator.pick_explore_goal)
                        finally:
                            s.nav_pending -= 1
                        if s.arb.owner != 'nav':
                            s.event('Exploration goal found but not started: control owner is %s' % s.arb.owner)
                            continue
                        if s.localization_blocked or generation != s.recovery_generation or s.nav is not navigator:
                            s.arb.release('nav', 'exploration abandoned')
                            continue
                        if goal is None:
                            s.arb.release('nav', 'no exploration goal')
                            s.event('Exploration goal selection failed: %s' % why)
                        else:
                            ok, why2 = s.nav.start_mission(goal)
                            if not ok:
                                s.arb.release('nav', 'exploration did not start')
                            s.event('Exploring: goal (%.2f, %.2f) %s; posture %s, speed limit %.2f m/s; '
                                    'returns to the start point on arrival' % (
                                        goal[0], goal[1], why, s.nav.mode, s.nav.v_max) if ok else why2)
            elif t == 'brain':
                mode = m.get('mode')
                if mode not in ('off', 'shadow', 'drive', 'reflex'):
                    s.event('Brain mode must be off, shadow, drive or reflex')
                elif mode == 'drive' and (s.nav is None or s.nav.active or not s.robot_status.get('chassis_running')):
                    s.event('Brain drive refused: needs the chassis running, a localized session and no navigation task')
                else:
                    if mode == 'drive':
                        ok, why0, ended = s.arb.request('brain', cid, cname, 'brain drive')
                        if not ok:
                            s.refuse(cid, why0)
                            continue
                        s.end_owner(ended, 'brain drive started')
                    elif s.arb.owner == 'brain':
                        s.arb.release('brain', 'brain mode %s' % mode)
                    why = s.brain.set_mode(mode, m.get('radius'), m.get('area'))
                    if why and mode == 'drive':
                        s.arb.release('brain', 'brain drive refused')
                    where = ''
                    if why:
                        pass
                    elif mode == 'reflex':
                        where = (' (fly reflexes: during navigation tasks the brain takes over to freeze or '
                                 'escape from unmapped objects; the planner then resumes)')
                    elif mode == 'drive' and s.brain.keepin:
                        where = ' (map keep-in, %.0f m2 of free floor)' % s.brain.keepin['area_m2']
                    elif mode == 'drive':
                        where = ' (geofence %.1f m around (%.2f, %.2f))' % (s.brain.fence[2], s.brain.fence[0], s.brain.fence[1])
                    s.event(why or ('Brain mode: %s%s' % (mode, where)))
                    if mode != 'drive':
                        s.cmd, s.cmd_at = (0.0, 0.0), 0.0
            elif t == 'nav_params' and s.nav is not None:
                apply_nav_params(s, m)
            elif t == 'cloud_submit' and s.nav is not None:
                await asyncio.get_event_loop().run_in_executor(None, s.nav.changes.submit)
            elif t == 'auto_submit' and s.nav is not None:
                s.nav.changes.auto_submit = bool(m.get('on'))
            elif t == 'posture':
                stand = bool(m.get('stand'))
                if s.nav is not None and s.nav.active:
                    s.event('Posture changes are refused while navigating; stop navigation first')
                elif not s.robot_status.get('chassis_running'):
                    s.event('The chassis driver is not running; posture cannot change')
                elif s.robot_status.get('posture_ready') is False:
                    s.event('Posture request not sent: %s'
                            % s.robot_status.get('posture_block_reason', 'robot-side guard not ready'))
                elif s.robot_status.get('operation_busy'):
                    s.event('Another robot operation is in progress; posture request not repeated')
                else:
                    ok, why, ended = s.arb.request('posture', cid, cname, 'stand' if stand else 'crouch')
                    if not ok:
                        s.refuse(cid, why)
                        continue
                    s.cmd = (0.0, 0.0)
                    s.cmd_at = 0.0
                    s.posture_baseline = (s.robot_status.get('posture_result') or {}).get('t')
                    sent = await s.send({'op': 'posture', 'stand': stand})
                    if not sent:
                        s.arb.release('posture', 'posture request not delivered')
                    s.event(('%s request sent; waiting for the chassis to confirm the posture' if sent
                             else '%s request was not delivered; check the clock anchor / connection')
                            % ('Stand' if stand else 'Crouch'))
            elif t == 'safety_reset':
                await s.send({'op': 'safety_reset'})
            elif t == 'retrace':
                # Operator-requested return along the path the robot actually drove.
                # Works without base-map localisation: the bridge replays its own
                # applied-command trace backwards, with the chassis guard still live.
                ok, why, ended = s.arb.request('retrace', cid, cname, 'return along the driven path')
                if not ok:
                    s.refuse(cid, why)
                    continue
                s.end_owner(ended, 'return along the driven path')
                s.retrace_seen = False
                if s.nav is not None and s.nav.active:
                    s.nav.cancel('Return along the driven path requested')
                s.cmd, s.cmd_at = (0.0, 0.0), 0.0
                await s.send({'op': 'cmd', 'v': 0, 'w': 0})
                await s.send({'op': 'retrace'})
                s.event('Requested a slow return along the driven path (robot-side limits stay active)')
            elif t == 'save' and (s.slam or s.last_slam):
                path = await asyncio.get_event_loop().run_in_executor(None, (s.slam or s.last_slam).save)
                s.event('Map saved: %s' % path)
    finally:
        app['clients'].discard(ws)
        s.end_owner(s.arb.client_lost(cid), 'controlling console disconnected')
        autonomous = s.nav is not None and s.nav.active
        if s.manual_client is ws:
            s.manual_client = None
            if not autonomous:
                s.cmd = (0.0, 0.0)
                s.cmd_at = 0.0
        if not app['clients']:
            s.clients_lost_at = s.clients_lost_at or time.time()
            if autonomous:
                s.event('Monitoring connection lost; the autonomous task continues on the server')
            else:
                s.cmd = (0.0, 0.0)
                s.cmd_at = 0.0
    return ws


async def download(request):
    s = request.app['session']
    name = request.match_info['name']
    if not s.run_dir or name not in ('map.ply', 'map_topdown.pgm', 'trajectory.csv', 'summary.json'):
        raise web.HTTPNotFound()
    p = s.run_dir / name
    if not p.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={'Content-Disposition': 'attachment; filename=%s' % name})


async def diagnostics(request):
    app = request.app
    return web.json_response({
        'session_running': app['session'].running,
        'status': app['session'].status(),
        'control_clients': len(app['clients']),
        'control_disconnect_since': app['session'].clients_lost_at,
        'tasks': {task.get_name(): not task.done() for task in app['tasks']},
        'errors': dict(app['background_errors']),
        'pipeline': app['session'].status().get('pipeline'),
        'transport_contract': {'motion_lease_s': CMD_LEASE_S, 'heartbeat_period_s': 0.25,
                               'remote_clock': None if app['session'].remote_clock is None else app['session'].remote_clock.status(),
                               'robot_host': app.get('robot_host'),
                               'remote_physical_motion_enabled': not app['session'].chassis_disabled,
                               'pose_age_basis': 'source_and_ingress',
                               'raw_overflow_policy': 'latch_fault_and_inhibit_motion'},
        'navigation': None if app['session'].nav is None else {
            'active': app['session'].nav.active,
            'reason': app['session'].nav.reason,
            'fitness': app['session'].nav.fitness,
            'tour_route_mode': 'whole_route' if app['session'].nav.leg == 'tour' else None,
            'tour_progress_m': app['session'].nav.tour_progress_m,
            'tour_length_m': None if app['session'].nav.tour_arc is None else float(app['session'].nav.tour_arc[-1]),
             'state': app['session'].nav.state,
             'detour_count': app['session'].nav.detour_count,
             'detour_reason': app['session'].nav.detour_reason,
             'last_detour': app['session'].nav.last_detour,
        },
    })


async def on_startup(app):
    app['loop'] = asyncio.get_event_loop()
    app['background_errors'] = {}

    def record_failure(task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            app['background_errors'][task.get_name()] = repr(error)
            traceback.print_exception(type(error), error, error.__traceback__)

    workers = {
        'control': control_loop,
        'heartbeat': heartbeat_loop,
        'display': publish_loop,
        'camera': camera_loop,
        'status': status_loop,
    }
    app['tasks'] = []
    for name, worker in workers.items():
        task = asyncio.create_task(worker(app), name=name)
        task.add_done_callback(record_failure)
        app['tasks'].append(task)


async def on_cleanup(app):
    await app['session'].stop()


def main():
    # `kill -USR1 <pid>` writes every thread's stack to logs/stacks.txt (no ptrace needed)
    import faulthandler
    import signal as _signal
    (ROOT / 'logs').mkdir(exist_ok=True)
    if hasattr(faulthandler, 'register'):         # POSIX only
        faulthandler.register(_signal.SIGUSR1, file=open(ROOT / 'logs' / 'stacks.txt', 'a'), all_threads=True)
    ap = argparse.ArgumentParser(description='Xingtian SLAM / navigation compute service')
    ap.add_argument('--robot-host', help='SSH destination of the robot (live sessions)')
    ap.add_argument('--robot-root', default=os.environ.get('XT_ROBOT_ROOT', ''),
                    help='absolute robot deployment root holding robot/run.sh')
    ap.add_argument('--replay', help='replay a raw.xt recording instead of a live robot')
    ap.add_argument('--speed', type=float, default=1.0, help='replay speed factor')
    ap.add_argument('--base', help='base map point cloud (.ply/.npy) to localize and continue mapping on')
    ap.add_argument('--nav', help='navigation package (map.pgm/map.yaml + layers) in the same frame as --base')
    ap.add_argument('--port', type=int, default=8091)
    ap.add_argument('--record-reserve-mib', type=int, default=8192,
                    help='free disk space kept in reserve while recording (at least 64 MiB)')
    a = ap.parse_args()
    if bool(a.robot_host) == bool(a.replay):
        ap.error('give exactly one of --robot-host or --replay')
    if a.robot_host and (a.robot_host.startswith('-') or not a.robot_root.startswith('/')):
        ap.error('robot host must not be an option and robot root must be absolute')
    if a.record_reserve_mib < 64:
        ap.error('--record-reserve-mib must be at least 64')
    app = web.Application()
    app['record_reserve_bytes'] = a.record_reserve_mib * 1024 * 1024
    app['clients'] = set()
    app['display_clients'] = set()
    app['camera_clients'] = set()
    app['base'] = None
    app['base_path'] = a.base
    app['nav_pkg'] = a.nav
    app['robot_host'] = a.robot_host
    if a.robot_host:
        # The robot bridge enforces the same two interlocks; both are passed explicitly.
        # XT_REMOTE_CONTROL=1 keeps bridges deployed before 2026-10-07 on the same rule.
        charging = '0' if os.environ.get('XT_CHASSIS_DISABLED', '1') == '0' else '1'
        remote_motion = '1' if os.environ.get('XT_REMOTE_MOTION_ENABLED', '0') == '1' else '0'
        remote_command = ('env XT_CHASSIS_DISABLED=' + charging + ' XT_REMOTE_CONTROL=1 '
                          'XT_REMOTE_MOTION_ENABLED=' + remote_motion + ' XT_MAX_V=%.2f bash ' % SPEED_LIMIT_MAX
                          + shlex.quote(a.robot_root + '/robot/run.sh'))
        app['robot_cmd'] = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                            '-o', 'StrictHostKeyChecking=yes', '-o', 'ServerAliveInterval=2',
                            '-o', 'ServerAliveCountMax=3', a.robot_host, remote_command]
        if os.environ.get('XT_ROBOT_CMD'):
            # offline test hook: a stand-in bridge (tools/fake_bridge.py) instead of SSH to the robot
            app['robot_cmd'] = shlex.split(os.environ['XT_ROBOT_CMD'])
            print('robot command overridden for testing:', app['robot_cmd'], flush=True)
    if a.base:
        def load():
            app['base'] = RL.BaseMap(RL.load_points(a.base))
            print('base map loaded', a.base, len(app['base'].pts), flush=True)
        threading.Thread(target=load, daemon=True).start()
    app['session'] = Session(app, replay=a.replay, speed=a.speed)
    app.router.add_get('/diagnostics', diagnostics)
    app.router.add_get('/ws', ws_handler)
    app.router.add_get('/stream', display_handler)
    app.router.add_get('/camera', camera_handler)
    app.router.add_get('/download/{name}', download)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host='127.0.0.1', port=a.port, print=lambda *x: print('listening', a.port, flush=True))


if __name__ == '__main__':
    main()
