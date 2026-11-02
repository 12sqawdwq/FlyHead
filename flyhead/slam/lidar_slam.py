"""LiDAR odometry + voxel map for Unitree L1 clouds (KISS-ICP backend).

Pose output is LiDAR odometry only (no loop closure); the map frame is the
LiDAR pose at session start, levelled by the IMU gravity estimate.
Motion within a frame is compensated for rotation only, using the L1's own
IMU orientation (KISS-ICP's constant-velocity deskew amplified static jitter:
y std 9 cm vs 1.8 cm on the 2026-09-25 static recording).
"""
from collections import deque
import csv
import json
import math
import threading
import time
from pathlib import Path

import numpy as np
from kiss_icp.config import KISSConfig
from kiss_icp.kiss_icp import KissICP
from scipy.spatial import cKDTree

from . import reloc as RL

ACC_S = 0.20            # L1 sub-clouds (~0.12 s, ~1.9k pts) are too sparse alone;
                        # 0.2 s gives ~2 cm static jitter (0.1 s diverged)
INIT_S = 2.0            # first frame: 2 s of points (robot static at start) as a dense seed map
MIN_RANGE = 0.40        # drop robot-body returns
MAX_RANGE = 25.0
DESKEW = False          # KISS constant-velocity deskew (off; IMU deskew instead)
IMU_DESKEW = True
IMU_WAIT_S = 0.5        # max wait for IMU to bracket a frame
IMU_PRIOR = True        # seed ICP rotation with the IMU-measured frame-to-frame rotation
VEL_DAMP = 0.5          # shrink the constant-velocity translation guess
KISS_THREADS = 4        # explicit native registration budget; not an OpenMP setting
VOXEL = 0.20            # KISS-ICP voxel; matched 0.10 m accuracy (1 cm end-point difference) at half the cost
MAP_VOXEL = 0.05        # display / export map resolution
MAX_MAP = 4_000_000
# LiDAR -> robot body yaw.  The L1 faces backwards: during forward-only commands
# the motion direction in the LiDAR frame was 178.2 deg (live_213534) and
# -179.7 deg (live_204520).  Poses/yaw/arrow are reported for the body (x = forward).
BODY_YAW_DEG = 180.0
# Robot body = sphere (operator choice, 2026-09-25).  Centre in the LiDAR frame is
# the middle of the persistent self returns seen while driving 51 m (live_204520:
# x -0.68..-0.32, y -0.62..0.52, z 0.02..0.43), i.e. 0.45 m ahead of the LiDAR.
# Points inside are not registered, mapped or treated as obstacles.
SELF_FILTER = True
BODY_CENTER_LIDAR = (-0.45, -0.05, 0.20)   # crouched posture; centre of the body-return filter only
# Turning point (the point fixed when the robot turns in place) in the LiDAR frame: 0.11 m
# behind the LiDAR along the body (LiDAR +x = body backward).  Same point as nav.REFERENCE_BODY;
# fitted from 47 in-place turns (2026-10-08).  Displayed pose and pose hints use it.
TURN_POINT_LIDAR = (0.11, 0.01, 0.0)
BODY_RADIUS = 0.50
# Learned self mask (per posture): LiDAR-frame voxels occupied in most frames while
# the robot moves are the robot itself.  Covers the standing posture (legs below the
# head-mounted LiDAR) without a separate calibration run.
SELF_LEARN = True
SELF_VOX = 0.05
SELF_RANGE = 1.2
SELF_RATIO = 0.6
SELF_MIN_FRAMES = 60


class SelfMask:
    def __init__(self):
        self.count = {}
        self.frames = 0
        self.mask = np.zeros(0, np.int64)

    @staticmethod
    def keys(xyz):
        q = np.floor(xyz / SELF_VOX).astype(np.int64) + (1 << 20)
        return (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]

    def update(self, xyz):
        near = xyz[np.linalg.norm(xyz, axis=1) < SELF_RANGE]
        for k in np.unique(self.keys(near)).tolist():
            self.count[k] = self.count.get(k, 0) + 1
        self.frames += 1
        if self.frames % 20 == 0 and self.frames >= SELF_MIN_FRAMES:
            self.mask = np.array(sorted(k for k, c in self.count.items() if c >= SELF_RATIO * self.frames), np.int64)
        if self.frames >= 400:                 # sliding window: halve history
            self.count = {k: c // 2 for k, c in self.count.items() if c > 1}
            self.frames //= 2

    def contains(self, xyz):
        if not len(self.mask):
            return np.zeros(len(xyz), bool)
        return np.isin(self.keys(xyz), self.mask)
RELOC_RADIUS = 15.0     # local submap used for relocalisation
RELOC_PERIOD = 1.5
RELOC_HINT_TTL_S = 300.0  # an operator pose hint expires after this
SEED_RADIUS = 12.0      # base-map points pushed into the KISS local map
SEED_EVERY_M = 2.0
MAP_INSERT_EVERY = 4     # insert every Nth registered frame into the saved session map
KISS_MAX_PTS_VOXEL = 6   # dense seeded voxels (20 points) made registration 1.7x slower
SEED_VOXEL = 0.25
# Continuous map correction.  Odometry alone drifts: the KISS local map keeps at most
# KISS_MAX_PTS_VOXEL points per voxel, and around the robot those voxels are filled by its
# own scans first, so the base-map seed points barely constrain the pose.  A standing tour
# drifted 0.62 m in 25 m (live_20261008T123504) until map agreement fell below the
# navigation limit.  About once per second the current scan is aligned to the base map
# (levelled ICP, yaw + translation); a confident, small result is applied in part to the
# session->map transform, so the pose converges to the map instead of jumping.
MAP_CORRECT_EVERY_S = 1.0
MAP_CORRECT_RADIUS = 8.0
MAP_CORRECT_VOXEL = 0.15
MAP_CORRECT_MAX_PTS = 3000
MAP_CORRECT_ITERS = 20
MAP_CORRECT_MIN_FIT = 0.70       # alignment fitness needed after ICP ...
MAP_CORRECT_MAX_STEP_M = 0.30    # ... and a correction no larger than this ...
MAP_CORRECT_MAX_YAW_DEG = 5.0    # ... and this
MAP_CORRECT_GAIN = 0.5           # fraction of an accepted correction applied
# Drift alarm: a correction rejected only for its size although it aligns well (the pose has
# slipped further than a continuous correction may move it; 2026-10-08 a 0.41 m fix with
# fitness 0.76 -> 0.97 was rejected while the robot drove on 0.5 m off).  DRIFT_COUNT such
# rejections in a row raise `drift` in the summary; the server then stops and relocalizes.
MAP_CORRECT_DRIFT_FIT = 0.85     # alignment fitness after ICP ...
MAP_CORRECT_DRIFT_GAIN = 0.05    # ... at least this much better than before ...
MAP_CORRECT_DRIFT_MAX_M = 2.0    # ... and a plausible size
MAP_CORRECT_DRIFT_COUNT = 2


def voxel_keys(p, size):
    q = np.floor(p / size).astype(np.int64) + (1 << 20)
    return (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]


def quat_to_rot(q):
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
                     2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
                     2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
                    axis=-1).reshape(q.shape[:-1] + (3, 3))


def align_to_z(a):
    """Rotation taking unit vector a onto +z."""
    a = a / np.linalg.norm(a)
    z = np.array([0., 0., 1.])
    v = np.cross(a, z)
    c = float(a @ z)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1., -1., -1.])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


class SlamEngine:
    """base: optional reloc.BaseMap.  With a base the session first runs
    odometry in its own frame, relocalises against the base in the background
    (growing local submap: drive a little if ambiguous), then switches to the
    base frame, seeds KISS-ICP with base points and keeps mapping on top."""

    def __init__(self, out_dir: Path, base=None, stop_event=None):
        self.out = Path(out_dir)
        cfg = KISSConfig()
        cfg.data.max_range = MAX_RANGE
        cfg.data.min_range = MIN_RANGE
        cfg.data.deskew = DESKEW
        cfg.mapping.voxel_size = VOXEL
        cfg.mapping.max_points_per_voxel = KISS_MAX_PTS_VOXEL
        cfg.adaptive_threshold.initial_threshold = 0.5
        cfg.adaptive_threshold.min_motion_th = 0.05
        cfg.registration.max_num_threads = KISS_THREADS
        self.kiss = KissICP(cfg)
        self.lock = threading.Lock()
        self.acc = []           # pending sub-clouds (stamp, pts)
        self.imu_acc = []
        self.imu = deque(maxlen=3000)   # (stamp, qx, qy, qz, qw)
        self.pending = deque()          # frames waiting for IMU coverage
        self.deskewed = self.undeskewed = 0
        self.R_end = None               # IMU orientation at the latest frame end
        self.R_prev = None
        self.gravity = None     # 4x4 levelling transform
        self.map_keys = set()
        self.map_chunks = []
        self.map_n = 0
        self.pose_out = None            # latest body pose (4x4) not yet published
        self.stage_ms = {}
        self.imu_deskew_ms = 0.0
        self.traj = []          # t, x, y, z, yaw
        self.frames = 0
        self.proc_ms = 0.0
        self.last_pts = 0
        self.dist = 0.0
        self.dist_anchor = np.zeros(3)
        self.last_error = None
        self.first_stamp = None
        self.frame_stamp = None
        self.input_received_at = None
        self.processing_started_at = None
        self.previous_frame_stamp = None
        self.previous_frame_dt = None
        self.pending_dropped = 0
        self.base = base
        self.body_T = np.eye(4)
        self.body_T[:2, :2] = RL.rot2(math.radians(BODY_YAW_DEG))
        self.Toff = np.eye(4)           # session levelled frame -> map frame
        self.attached = base is None
        self.pending_Toff = None
        self.local_chunks = []          # pre-attach points, session levelled frame
        self.local_traj = []
        self.reset_view = False
        self.seed_at = None
        self.correct_job = None          # (world points, wall time) for the correction thread
        self.correct_result = None       # 4x4 map-frame correction waiting to be applied
        self.correct_evt = threading.Event()
        self.correct_last = 0.0
        self.correct_info = dict(applied=0, rejected=0, last=None, drift=None, drift_events=0)
        self.drift_run = 0
        self.stop_evt = threading.Event() if stop_event is None else stop_event
        self.reloc_info = None
        self.reloc_hint = None          # operator pose hint (x, y, yaw|None, expires_at)
        self.on_frame = None            # callback(Wb, sensor_xyz, world, fitness) after attach
        self.mode = 'crouch'            # posture, set by the navigator from LiDAR height above floor
        self.self_masks = {'crouch': SelfMask(), 'stand': SelfMask()}
        self.fitness = None             # live scan vs base map agreement (base sessions)
        if base is not None:
            self.seed_pts = RL.voxel(base.mv, SEED_VOXEL)
            self.seed_tree = cKDTree(self.seed_pts[:, :2])
            self.preload(base.pts)
            self.reloc_info = dict(state='searching', tries=0)
            threading.Thread(target=self.reloc_loop, daemon=True).start()
            threading.Thread(target=self.correct_loop, daemon=True).start()

    # ---------- inputs ----------
    def add_imu(self, samples, process_pending=True):
        for smp in samples:
            if not self.imu or smp[0] > self.imu[-1][0]:
                self.imu.append(smp[:5])
        if process_pending:
            self.drain()
        if self.gravity is None:
            self.imu_acc.extend(s[8:11] for s in samples)
            if len(self.imu_acc) >= 100:
                a = np.mean(np.array(self.imu_acc), axis=0)
                G = np.eye(4)
                G[:3, :3] = align_to_z(a)
                self.gravity = G
                self.gravity_info = dict(acc_mean=a.tolist(), g_norm=float(np.linalg.norm(a)),
                                         tilt_deg=math.degrees(math.acos(max(-1, min(1, a[2] / np.linalg.norm(a))))))

    def add_cloud(self, stamp, pts):
        pts = pts[np.isfinite(pts).all(axis=1)]
        if not len(pts):
            return
        self.acc.append((stamp, pts))
        t0 = self.acc[0][0] + float(self.acc[0][1][:, 4].min())
        t1 = stamp + float(pts[:, 4].max())
        if t1 - t0 < (INIT_S if self.frames == 0 else ACC_S):
            return
        if self.gravity is None:          # wait for levelling; keep latest only
            self.acc = self.acc[-1:]
            return
        frame = np.concatenate([p[:, :3] for _, p in self.acc]).astype(np.float64)
        times = np.concatenate([s + p[:, 4].astype(np.float64) for s, p in self.acc])
        self.acc = []
        # Retain one complete scan, not an arbitrarily truncated sub-cloud.
        self.pending_dropped += len(self.pending)
        self.pending.clear()
        self.pending.append((frame, times, self.input_received_at))
        self.drain(newest=t1)

    def drain(self, newest=None):
        """Process queued frames once the IMU covers them (or give up waiting)."""
        while self.pending:
            frame, times, received_at = self.pending[0]
            covered = (bool(self.imu) and self.imu[0][0] <= times.min()
                       and self.imu[-1][0] >= times.max())
            stale = newest is not None and newest - times.max() > IMU_WAIT_S
            if not (covered or stale or not IMU_DESKEW):
                return
            self.pending.popleft()
            # Bind the age origin to this frame, including its IMU deskew work.
            self.processing_started_at = time.time()
            started = time.perf_counter()
            if IMU_DESKEW and covered:
                frame = self.imu_deskew(frame, times)
            else:
                self.undeskewed += 1
            self.imu_deskew_ms = (time.perf_counter() - started) * 1000
            self.input_received_at = received_at
            self.process(frame, times)

    def imu_deskew(self, xyz, times):
        """Rotate every point into the LiDAR orientation at the frame end time."""
        imu = np.array(self.imu)
        ts, qs = imu[:, 0], imu[:, 1:5].copy()
        # Vectorized hemisphere continuity. An exactly orthogonal pair resets
        # sign propagation, matching the scalar rule's strict '< 0' comparison.
        if len(qs) > 1:
            dots = np.einsum('ij,ij->i', qs[1:], qs[:-1])
            parity = np.cumsum(dots < 0)
            resets = np.maximum.accumulate(np.where(dots == 0, np.arange(len(dots)), -1))
            baseline = np.where(resets < 0, 0, parity[np.maximum(resets, 0)])
            qs[1:] *= np.where((parity - baseline) % 2, -1.0, 1.0)[:, None]
        t_end = times.max()
        # Preserve both interpolation brackets, not the full 15-second history.
        first = max(0, int(np.searchsorted(ts, times.min(), side='right')) - 1)
        last = min(len(ts), int(np.searchsorted(ts, t_end, side='left')) + 1)
        ts, qs = ts[first:last], qs[first:last]
        q = np.stack([np.interp(times, ts, qs[:, k]) for k in range(4)], axis=1)
        q_end = np.array([np.interp(t_end, ts, qs[:, k]) for k in range(4)])
        R = quat_to_rot(q)
        R_end = quat_to_rot(q_end)
        self.R_end = R_end
        rel = np.einsum('ji,njk->nik', R_end, R)      # R_end^T R(t)
        self.deskewed += 1
        return np.einsum('nij,nj->ni', rel, xyz)

    # ---------- base map / relocalisation ----------
    def preload(self, pts):
        keys = voxel_keys(pts, MAP_VOXEL)
        keys, idx = np.unique(keys, return_index=True)
        self.map_keys.update(keys.tolist())
        chunk = pts[idx].astype(np.float32)
        self.map_chunks.append(chunk)
        self.map_n += len(chunk)
        self.reset_view = True

    def reloc_loop(self):
        while not self.stop_evt.wait(RELOC_PERIOD) and not self.attached and self.pending_Toff is None:
            with self.lock:
                chunks = list(self.local_chunks)
                pose = self.local_traj[-1] if self.local_traj else None
                path = self.dist
            if pose is None or not chunks:
                continue
            pts = np.concatenate(chunks)
            near = pts[np.linalg.norm(pts[:, :2] - np.array(pose[1:3]), axis=1) < RELOC_RADIUS]
            # session turning point (TURN_POINT_LIDAR; LiDAR axes = body axes rotated 180 deg)
            yaw = pose[4]
            body = (pose[1] - TURN_POINT_LIDAR[0] * math.cos(yaw) + TURN_POINT_LIDAR[1] * math.sin(yaw),
                    pose[2] - TURN_POINT_LIDAR[0] * math.sin(yaw) - TURN_POINT_LIDAR[1] * math.cos(yaw), yaw)
            hint = self.reloc_hint
            if hint is not None and time.time() > hint[3]:
                hint = self.reloc_hint = None
            tic = time.perf_counter()
            try:
                r = self.base.localize(near, hint=None if hint is None else hint[:3], body=body)
            except Exception as exc:
                self.reloc_info = dict(self.reloc_info, error=repr(exc))
                continue
            info = dict(state='searching', tries=self.reloc_info['tries'] + 1, points=len(near),
                        local_path_m=round(path, 2), secs=round(time.perf_counter() - tic, 1))
            if r.get('best'):
                info.update(fitness=r['best']['fitness'], rmse=r['best']['rmse'],
                            ratio=round(min(r['ratio'], 99.0), 2),
                            second=r['second'] and r['second']['fitness'],
                            hinted=r['hinted'], hint=None if hint is None else list(hint[:3]),
                            candidates=[{k: c[k] for k in ('fitness', 'robot') if k in c}
                                        for c in r['candidates'][:3]])
            self.reloc_info = info
            if r['confident']:
                self.pending_Toff = r['best']['T']

    def set_reloc_hint(self, x, y, yaw=None, ttl=RELOC_HINT_TTL_S):
        """Operator pose of the robot body on the base map, used by the next searches."""
        self.reloc_hint = (float(x), float(y), None if yaw is None else float(yaw), time.time() + ttl)

    def correct_loop(self):
        """Align queued scans to the base map; publish accepted corrections."""
        while not self.stop_evt.is_set():
            if not self.correct_evt.wait(0.5):
                continue
            self.correct_evt.clear()
            job, self.correct_job = self.correct_job, None
            if job is None:
                continue
            world, centre = job
            try:
                near = world[np.linalg.norm(world[:, :2] - centre[:2], axis=1) < MAP_CORRECT_RADIUS]
                src = RL.voxel(near, MAP_CORRECT_VOXEL)
                if len(src) < 200:
                    continue
                if len(src) > MAP_CORRECT_MAX_PTS:
                    src = src[np.random.default_rng(0).choice(len(src), MAP_CORRECT_MAX_PTS, replace=False)]
                before = float((self.base.tree.query(src)[0] < 0.15).mean())
                T, fit, _ = RL.icp(self.base.tree, self.base.mv, src, np.eye(4), iters=MAP_CORRECT_ITERS)
                step = float(np.linalg.norm(T[:3, 3]))
                yaw = math.degrees(math.atan2(T[1, 0], T[0, 0]))
                info = dict(fit_before=round(before, 3), fit_after=round(fit, 3), dx=round(float(T[0, 3]), 3),
                            dy=round(float(T[1, 3]), 3), dz=round(float(T[2, 3]), 3), dyaw_deg=round(yaw, 2))
                ok = (fit >= MAP_CORRECT_MIN_FIT and fit >= before - 0.01
                      and step <= MAP_CORRECT_MAX_STEP_M and abs(yaw) <= MAP_CORRECT_MAX_YAW_DEG)
                large = (not ok and fit >= MAP_CORRECT_DRIFT_FIT and fit >= before + MAP_CORRECT_DRIFT_GAIN
                         and step <= MAP_CORRECT_DRIFT_MAX_M
                         and (step > MAP_CORRECT_MAX_STEP_M or abs(yaw) > MAP_CORRECT_MAX_YAW_DEG))
                with self.lock:
                    self.drift_run = self.drift_run + 1 if large else 0
                    if self.drift_run >= MAP_CORRECT_DRIFT_COUNT:
                        if self.correct_info.get('drift') is None:
                            self.correct_info['drift_events'] += 1
                        self.correct_info['drift'] = dict(info, t=time.time(), step_m=round(step, 3),
                                                          event=self.correct_info['drift_events'])
                    elif not large:
                        self.correct_info['drift'] = None
                    if ok:
                        self.correct_result = T
                        self.correct_info['applied'] += 1
                    else:
                        self.correct_info['rejected'] += 1
                    self.correct_info['last'] = dict(info, accepted=ok)
            except Exception as exc:
                self.correct_info['error'] = repr(exc)

    def apply_correction(self):
        """Fold a pending map correction (fraction MAP_CORRECT_GAIN) into Toff."""
        with self.lock:
            T, self.correct_result = self.correct_result, None
        if T is None:
            return
        yaw = math.atan2(T[1, 0], T[0, 0]) * MAP_CORRECT_GAIN
        part = np.eye(4)
        part[:2, :2] = RL.rot2(yaw)
        part[:3, 3] = T[:3, 3] * MAP_CORRECT_GAIN
        self.Toff = part @ self.Toff

    def attach(self, T):
        """Switch from the session frame to the base frame (called by the SLAM thread)."""
        self.Toff = np.asarray(T, np.float64)
        R, t = self.Toff[:3, :3], self.Toff[:3, 3]
        dyaw = math.atan2(R[1, 0], R[0, 0])
        with self.lock:
            if self.local_chunks:
                self.insert_map(np.concatenate(self.local_chunks) @ R.T + t)
            self.traj = [(st, *(R @ np.array([x, y, z]) + t).tolist(), math.remainder(yw + dyaw, 2 * math.pi))
                         for st, x, y, z, yw in self.local_traj]
            self.local_chunks = []
            self.attached = True
            self.dist_anchor = np.array(self.traj[-1][1:4]) if self.traj else np.zeros(3)
            self.reset_view = True
        self.reloc_info = dict(self.reloc_info, state='attached',
                               T=[round(v, 4) for v in self.Toff.ravel().tolist()])

    def seed(self, pos):
        """Push base-map points around `pos` (map frame) into the KISS local map."""
        idx = self.seed_tree.query_ball_point(pos[:2], SEED_RADIUS)
        if not idx:
            return
        A = self.Toff @ self.gravity            # KISS frame -> map frame
        Ainv = np.linalg.inv(A)
        p = self.seed_pts[idx] @ Ainv[:3, :3].T + Ainv[:3, 3]
        self.kiss.local_map.add_points(np.ascontiguousarray(p, np.float64))
        self.seed_at = np.array(pos[:2])

    def close(self):
        self.stop_evt.set()

    def take_reset(self):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            reset, self.reset_view = self.reset_view, False
            return reset
        finally:
            self.lock.release()

    # ---------- odometry ----------
    def process(self, xyz, times):
        tic = time.perf_counter()
        r = np.linalg.norm(xyz, axis=1)
        keep = (r > MIN_RANGE) & (r < MAX_RANGE)
        if SELF_LEARN:
            sm = self.self_masks[self.mode]
            moving = np.linalg.norm(self.kiss.last_delta[:3, 3]) > 0.01 or \
                abs(math.atan2(self.kiss.last_delta[1, 0], self.kiss.last_delta[0, 0])) > 0.01
            if moving and self.frames > 5:
                sm.update(xyz)
            keep &= ~sm.contains(xyz)
        if SELF_FILTER and self.mode == 'crouch':
            keep &= np.linalg.norm(xyz - np.array(BODY_CENTER_LIDAR), axis=1) > BODY_RADIUS
        xyz, times = xyz[keep], times[keep]
        if len(xyz) < 200:
            self.last_error = 'too few points (%d)' % len(xyz)
            return
        frame_stamp = float(times.max())
        interval = None if self.previous_frame_stamp is None else frame_stamp - self.previous_frame_stamp
        span = times.max() - times.min()
        tn = (times - times.min()) / span if span > 0 else np.zeros_like(times)
        if IMU_PRIOR and self.R_end is not None and self.R_prev is not None:
            # lidar-frame rotation between consecutive frame ends, measured by the IMU
            d = self.kiss.last_delta.copy()
            d[:3, :3] = self.R_prev.T @ self.R_end
            # A skipped scan changes elapsed time, not the estimated velocity.
            ratio = 1.0
            if interval is not None and interval > 0 and self.previous_frame_dt:
                ratio = float(np.clip(interval / self.previous_frame_dt, 0.25, 3.0))
            d[:3, 3] *= VEL_DAMP * ratio
            self.kiss.last_delta = d
        self.R_prev = self.R_end
        if self.pending_Toff is not None and not self.attached:
            self.attach(self.pending_Toff)
        if self.base is not None and self.attached:
            self.apply_correction()
            pos_now = (self.Toff @ self.gravity @ self.kiss.last_pose)[:3, 3]
            if self.seed_at is None or np.linalg.norm(pos_now[:2] - self.seed_at) > SEED_EVERY_M:
                self.seed(pos_now)
        registration_start = time.perf_counter()
        frame, _ = self.kiss.register_frame(xyz, tn)
        registration_end = time.perf_counter()
        self.frame_stamp = frame_stamp
        self.previous_frame_stamp = frame_stamp
        if interval is not None and interval > 0:
            self.previous_frame_dt = interval
        W = self.Toff @ self.gravity @ self.kiss.last_pose
        world = frame @ W[:3, :3].T + W[:3, 3]
        self.first_stamp = self.first_stamp or float(times.max())
        pos = W[:3, 3].copy()
        Wb = W @ self.body_T                        # robot body pose (x forward)
        yaw = math.atan2(Wb[1, 0], Wb[0, 0])
        map_start = time.perf_counter()
        with self.lock:
            chord = float(np.linalg.norm(pos - self.dist_anchor))
            if chord >= 0.05:        # ignore registration jitter in the odometer
                self.dist += chord
                self.dist_anchor = pos
            if not self.attached:     # base session, not yet relocalised: keep local
                self.local_traj.append((float(times.max()), *pos.tolist(), yaw))
                self.local_chunks.append(RL.voxel(world, 0.1))
                self.frames += 1
                self.last_pts = len(xyz)
                return
            self.traj.append((float(times.max()), *pos.tolist(), yaw))
            if self.frames % MAP_INSERT_EVERY == 0:
                self.insert_map(world)
            # Display pose at the turning point (what navigation controls): a pose away from
            # it swings sideways on every turn and the drawn trail leaves the path.
            display = Wb.copy()
            display[:3, 3] = W[:3, :3] @ np.array(TURN_POINT_LIDAR) + W[:3, 3]
            self.pose_out = display.astype(np.float32)
        fitness_start = time.perf_counter()
        # A small query per processed pose avoids reusing one low score across
        # multiple poses and mistaking slow computation for sustained mismatch.
        if self.base is not None and time.time() - self.correct_last >= MAP_CORRECT_EVERY_S:
            self.correct_last = time.time()
            self.correct_job = (world, pos)
            self.correct_evt.set()
        if self.base is not None:
            q = world[np.random.choice(len(world), min(400, len(world)), False)]
            dd, _ = self.base.tree.query(q)
            self.fitness = float((dd < 0.15).mean())
        self.stage_ms = dict(
            imu_deskew=self.imu_deskew_ms,
            prepare=(registration_start - tic) * 1000,
            registration=(registration_end - registration_start) * 1000,
            map_insert=(fitness_start - map_start) * 1000,
            fitness=(time.perf_counter() - fitness_start) * 1000,
        )
        if self.on_frame is not None:
            try:
                self.on_frame(Wb, W[:3, 3].copy(), world, self.fitness)
            except Exception as exc:
                self.last_error = 'nav: %r' % exc
        self.frames += 1
        self.last_pts = len(xyz)
        self.proc_ms = 0.9 * self.proc_ms + 0.1 * (time.perf_counter() - tic) * 1000 if self.frames > 1 else \
            (time.perf_counter() - tic) * 1000
        self.last_error = None

    def insert_map(self, world):
        if self.map_n >= MAX_MAP:
            return
        keys = voxel_keys(world, MAP_VOXEL)
        keys, idx = np.unique(keys, return_index=True)
        new = [i for k, i in zip(keys.tolist(), idx.tolist()) if k not in self.map_keys]
        if not new:
            return
        self.map_keys.update(keys.tolist())
        pts = world[new].astype(np.float32)
        self.map_chunks.append(pts)
        self.map_n += len(pts)

    # ---------- outputs ----------
    def take_pose(self):
        with self.lock:
            pose, self.pose_out = self.pose_out, None
        return pose

    def full_map(self):
        with self.lock:
            return np.concatenate(self.map_chunks) if self.map_chunks else np.zeros((0, 3), np.float32)

    def summary(self):
        pose = self.traj[-1] if self.traj else None
        sigma = None
        try:
            sigma = float(self.kiss.adaptive_threshold.get_threshold())
        except Exception:
            pass
        return dict(frames=self.frames, deskewed=self.deskewed, undeskewed=self.undeskewed, proc_ms=round(self.proc_ms, 1), points=self.last_pts,
                    map_points=self.map_n, distance_m=round(self.dist, 2), sigma=sigma,
                    pose=None if pose is None else [round(v, 3) for v in pose[1:]],
                    levelled=self.gravity is not None,
                    base=self.base is not None, attached=self.attached, reloc=self.reloc_info,
                    map_correction=dict(self.correct_info),
                    fitness=None if self.fitness is None else round(self.fitness, 3),
                    mode=self.mode, self_mask_voxels={k: int(len(m.mask)) for k, m in self.self_masks.items()},
                    gravity=getattr(self, 'gravity_info', None), error=self.last_error)

    def save(self, output=None, wait_until_idle=None, frozen_summary=None):
        out = Path(output) if output is not None else self.out
        out.mkdir(parents=True, exist_ok=True)
        if wait_until_idle is not None:
            wait_until_idle()
        pts = self.full_map()
        if wait_until_idle is not None:
            wait_until_idle()
        with open(out / 'map.ply', 'wb') as f:
            f.write(('ply\nformat binary_little_endian 1.0\nelement vertex %d\n'
                     'property float x\nproperty float y\nproperty float z\nend_header\n' % len(pts)).encode())
            f.write(pts.astype('<f4').tobytes())
        if wait_until_idle is not None:
            wait_until_idle()
        with self.lock:
            traj = list(self.traj)
        with open(out / 'trajectory.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['stamp', 'x', 'y', 'z', 'yaw'])
            w.writerows(traj)
        if wait_until_idle is not None:
            wait_until_idle()
        if len(pts) > 100:
            self.topdown(pts, output=out)
        if wait_until_idle is not None:
            wait_until_idle()
        summary = self.summary() if frozen_summary is None else frozen_summary
        (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        return str(out)

    def topdown(self, pts, res=0.05, output=None):
        out = Path(output) if output is not None else self.out
        z = pts[:, 2]
        floor = float(np.percentile(z, 2))
        band = (z > floor + 0.15) & (z < floor + 1.5)
        lo = pts[:, :2].min(axis=0)
        ij = np.floor((pts[:, :2] - lo) / res).astype(int)
        h, w = ij[:, 1].max() + 1, ij[:, 0].max() + 1
        img = np.full((h, w), 205, np.uint8)
        img[ij[:, 1], ij[:, 0]] = 254
        img[ij[band, 1], ij[band, 0]] = 0
        img = np.flipud(img)
        with open(out / 'map_topdown.pgm', 'wb') as f:
            f.write(b'P5\n%d %d\n255\n' % (w, h) + img.tobytes())
        (out / 'map_topdown.json').write_text(json.dumps(dict(
            resolution=res, origin=lo.tolist(), floor_z=floor, band=[floor + .15, floor + 1.5])))
