"""Stand-in for robot/run.sh: speaks the bridge protocol on stdin/stdout with a kinematic robot, so the
control server's ownership state machine can be exercised end to end without hardware.

  XT_ROBOT_CMD="python tools/fake_bridge.py --map runs/real_console_map --log runs/fake/ops.jsonl" \
      python -m flyhead.server.app --robot-host fake --robot-root /unused --base ... --nav ... --port 18091

Not a robot model. The pose integrates the accepted (v, w) with the bridge's lease rule (deadline_mono,
0.3 s, XT_MAX_V); clouds are taken from the map package's saved cloud occluded by its grid
(tools/make_synthetic_raw.cloud_frame), 10 Hz; IMU 200 Hz; status 5 Hz. The chassis starts crouched;
a posture request confirms after 1.5 s (FAKE_POSTURE=fail reports `failed`, as TRANSFORM UP FAIL did).
A retrace drives nothing and finishes after 3 s. Every received operation goes to --log (jsonl), the
record of who commanded what. Writing a percentage to <log>.battery sets the reported battery.
"""
import argparse
import json
import math
import os
import queue
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_synthetic_raw import LIDAR_H, WALL_TOP, cloud_frame  # noqa: E402

LEASE_S = 0.3
MAX_V = float(os.environ.get('XT_MAX_V', '0.10'))
MAX_W = 1.0
CHASSIS_DISABLED = os.environ.get('XT_CHASSIS_DISABLED', '1') != '0'


class Fake:
    def __init__(self, a):
        from flyhead.slam.navmap import NavMap
        from flyhead.slam.reloc import load_points
        nm = NavMap(a.map)
        self.grid, self.res, self.ox, self.oy = nm.blocked_for(0.32), nm.res, nm.origin[0], nm.origin[1]
        pts = load_points(str(Path(a.map) / 'map.ply'))
        self.cloud = pts[(pts[:, 2] > -LIDAR_H - 0.1) & (pts[:, 2] < WALL_TOP)]
        self.x, self.y, self.yaw = a.start          # LiDAR pose; body faces yaw + pi (rear-facing LiDAR)
        self.v = self.w = 0.0
        self.cmd_until = 0.0
        self.last_sequence = -1
        self.rejected = 0
        self.chassis = False
        self.mode = 2                               # robot_mode: 2 crouched, 3 standing
        self.posture = dict(state='idle', ok=None)
        self.busy_until = 0.0
        self.retrace_until = 0.0
        self.retrace_done = False
        self.out = queue.Queue(maxsize=400)
        self.lock = threading.Lock()
        self.log = open(a.log, 'a', buffering=1) if a.log else None
        self.rng = np.random.default_rng(7)
        self.az = np.linspace(-math.pi, math.pi, 360, endpoint=False)
        self.steps = np.arange(0.2, 12.0, 0.02)
        self.battery = float(os.environ.get('FAKE_BATTERY', '70'))
        self.battery_file = Path(a.log + '.battery') if a.log else None   # test override: write a percentage

    # ------------------------------------------------------------------ output
    def emit(self, kind, payload):
        try:
            self.out.put_nowait(b'XT' + struct.pack('<BI', kind, len(payload)) + payload)
        except queue.Full:
            pass

    def emit_json(self, obj):
        self.emit(3, json.dumps(obj).encode())

    def writer(self):
        out = sys.stdout.buffer
        while True:
            frame = self.out.get()
            try:
                out.write(frame)
                out.flush()
            except (BrokenPipeError, OSError):
                os._exit(0)

    # ------------------------------------------------------------------ input
    def record(self, obj, accepted, note=''):
        if self.log:
            self.log.write(json.dumps(dict(t=time.time(), mono=time.monotonic(), op=obj.get('op'), accepted=accepted,
                                           note=note, **{k: obj[k] for k in ('v', 'w', 'stand', 'on', 'sequence')
                                                         if k in obj})) + '\n')

    def reader(self):
        for line in sys.stdin:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            op, now = obj.get('op'), time.monotonic()
            if op == 'ping':
                if isinstance(obj.get('clock_token'), str):
                    self.emit_json(dict(event='clock', clock_token=obj['clock_token'], mono=now, wall=time.time()))
                continue
            if op == 'quit':
                os._exit(0)
            seq, deadline = obj.get('sequence', -1), obj.get('deadline_mono')
            valid = (isinstance(seq, int) and seq > self.last_sequence and isinstance(deadline, (int, float))
                     and 0 < deadline - now <= 2.1)
            if isinstance(seq, int):
                self.last_sequence = max(self.last_sequence, seq)
            with self.lock:
                if op == 'cmd':
                    v, w = float(obj.get('v', 0)), float(obj.get('w', 0))
                    ok = (valid and deadline - now <= LEASE_S + 0.01 and not CHASSIS_DISABLED and self.chassis
                          and now >= self.busy_until and now >= self.retrace_until)
                    if not ok:
                        v = w = 0.0
                        self.rejected += 1
                    self.v, self.w = max(-MAX_V, min(MAX_V, v)), max(-MAX_W, min(MAX_W, w))
                    self.cmd_until = min(deadline, now + LEASE_S) if ok and (v or w) else 0.0
                    if v or w or obj.get('v') or obj.get('w'):
                        self.record(obj, ok)
                    continue
                self.record(obj, valid)
                if not valid:
                    self.rejected += 1
                    self.emit_json(dict(event='error', error='expired/unversioned operation: %s' % op))
                    continue
                self.v = self.w = self.cmd_until = 0.0
                if op == 'chassis':
                    if obj.get('on') and CHASSIS_DISABLED:
                        self.emit_json(dict(event='error', error='charging debug: chassis operations disabled'))
                    else:
                        self.chassis = bool(obj.get('on'))
                        self.emit_json(dict(event='chassis', ok=True, fake=True, stopped=not self.chassis))
                elif op == 'posture':
                    threading.Thread(target=self.do_posture, args=(bool(obj.get('stand')),), daemon=True).start()
                elif op == 'retrace':
                    self.retrace_until, self.retrace_done = now + 3.0, False
                    self.emit_json(dict(event='link_return', active=True, trigger='operator', fake=True))
                elif op == 'camera':
                    self.emit_json(dict(event='camera', ok=False, error='fake bridge has no camera'))

    def do_posture(self, stand):
        if not self.chassis:
            return self.report_posture(stand, 'rejected', False, 'chassis driver is not running')
        self.busy_until = time.monotonic() + 1.6
        self.report_posture(stand, 'confirming', None, 'fake transition')
        time.sleep(1.5)
        if os.environ.get('FAKE_POSTURE') == 'fail':
            return self.report_posture(stand, 'failed', False, 'fake: TRANSFORM %s FAIL' % ('UP' if stand else 'DOWN'))
        self.mode = 3 if stand else 2
        self.report_posture(stand, 'confirmed', True, 'fake')

    def report_posture(self, stand, state, ok, note):
        self.posture = dict(state=state, ok=ok, stand=stand, note=note, t=time.time())
        self.emit_json(dict(event='posture', **self.posture))

    # ------------------------------------------------------------------ world
    def scan(self, t):
        d = np.c_[np.cos(self.az + self.yaw), np.sin(self.az + self.yaw)]
        pts = np.array([self.x, self.y]) + d[:, None, :] * self.steps[None, :, None]
        ij = np.floor((pts - [self.ox, self.oy]) / self.res).astype(int)
        ok = (ij[..., 0] >= 0) & (ij[..., 0] < self.grid.shape[0]) & (ij[..., 1] >= 0) & (ij[..., 1] < self.grid.shape[1])
        hit = np.zeros(ok.shape, bool)
        hit[ok] = self.grid[ij[..., 0][ok], ij[..., 1][ok]]
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
        wall = np.where(first >= 0, self.steps[np.maximum(first, 0)], 11.0)
        c = cloud_frame(self.cloud, self.x, self.y, self.yaw, self.az, wall, None, self.rng)
        self.emit(1, struct.pack('<dI', t, len(c)) + c.tobytes())

    def status(self):
        now = time.monotonic()
        if self.battery_file is not None and self.battery_file.exists():
            try:
                self.battery = float(self.battery_file.read_text())
            except ValueError:
                pass
        returning = now < self.retrace_until
        if not returning and self.retrace_until and not self.retrace_done:
            self.retrace_done = True
        self.emit_json(dict(
            event='status', t=time.time(), fake=True, chassis_disabled=CHASSIS_DISABLED,
            capabilities=['command-deadline-v1', 'clock-echo-v1', 'posture-confirmation-v1', 'link-loss-return-v1'],
            link_return=dict(active=returning, done=self.retrace_done, trigger='operator' if self.retrace_until else None,
                             result='done' if self.retrace_done else None, trace_samples=0, driven_m=0.0),
            command_rejected=self.rejected, last_sequence=self.last_sequence, operation_busy=now < self.busy_until,
            posture_ready=self.chassis, posture_block_reason=None if self.chassis else 'chassis driver is not running',
            posture_result=dict(self.posture), lidar_running=True, chassis_running=self.chassis, camera_running=False,
            body=dict(ctrl_mode=1, robot_mode=self.mode, error=0, warning=0, age=0.02) if self.chassis else None,
            battery=dict(voltage=round(21 + self.battery * 0.04, 2), pct=self.battery, age=0.1) if self.chassis else None,
            safety=dict(fresh=True, imu_fresh=True), cmd=[self.v, self.w] if now < self.cmd_until else [0, 0],
            max_v=MAX_V))

    def run(self):
        threading.Thread(target=self.writer, daemon=True).start()
        threading.Thread(target=self.reader, daemon=True).start()
        k, nxt = 0, time.monotonic()
        while True:
            nxt += 0.005
            time.sleep(max(0.0, nxt - time.monotonic()))
            now, t = time.monotonic(), time.time()
            with self.lock:
                v, w = (self.v, self.w) if now < self.cmd_until else (0.0, 0.0)
            heading = self.yaw + math.pi
            self.x += v * math.cos(heading) * 0.005
            self.y += v * math.sin(heading) * 0.005
            self.yaw += w * 0.005
            q = (0.0, 0.0, math.sin(self.yaw / 2), math.cos(self.yaw / 2))
            self.emit(2, struct.pack('<d10f', t, *q, 0.0, 0.0, w, 0.0, 0.0, 9.81))
            if k % 20 == 0:
                self.scan(t)
            if k % 40 == 0:
                self.status()
            k += 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--map', required=True, help='map package in the start frame (with map.ply)')
    ap.add_argument('--start', type=float, nargs=3, default=(0.0, 0.0, 0.0), metavar=('X', 'Y', 'YAW'))
    ap.add_argument('--log', help='jsonl record of every received operation')
    Fake(ap.parse_args()).run()
