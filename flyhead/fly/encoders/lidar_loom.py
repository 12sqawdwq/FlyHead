"""LiDAR virtual retina: obstacle points around the robot -> loom and free-space signals.

ENGINEERING PROXY, not retinal reconstruction. Per scan (body frame: x forward, y left):
  * the horizontal field is cut into SECTORS bins; each bin keeps a robust near range
    (10th percentile of returns, capped at RANGE_MAX);
  * every object is given a nominal width OBJECT_W, so a range d subtends
    theta = 2 atan(OBJECT_W / 2d); loom = d(theta)/dt > 0 (expansion while approaching);
  * bins are differenced in a WORLD-aligned frame (pose yaw), so turning in place does not
    read as loom; only approach (own translation or a moving object) does;
  * field side: azimuth > 0 (robot left) -> 'left', < 0 -> 'right'. Which anatomical eye each
    field side drives is a separate table (EYE_OF_FIELD), a calibration item.
Outputs are firing rates (Hz) per input cell type and side, plus the features they came from.
"""
import math

import numpy as np

SECTORS = 24                      # 15 deg bins
RANGE_MAX = 6.0                   # m
RANGE_MIN = 0.30                  # m, closer returns are body residue
OBJECT_W = 0.30                   # m, nominal object width for angular size
FRONT_HALF_DEG = 30.0             # free-space window for the LC9 forward drive
LOOM_GAIN_HZ_PER_RAD_S = 600.0    # 0.33 rad/s expansion (0.3 m/s toward a wall at 0.5 m) -> 200 Hz
LPLC2_MIN_THETA_DEG = 20.0        # LPLC2 driven only by large (near) expanding objects
LC9_MAX_HZ = 120.0                # below the old 200 Hz ceiling that saturated video_004
LC9_FREE_FULL_M = 2.5             # free space ahead at which LC9 drive is full
LC9_FREE_ZERO_M = 0.5             # ... and zero
MAX_RATE_HZ = 200.0
EYE_OF_FIELD = {'left': 'left', 'right': 'right'}   # field side -> anatomical side (uncalibrated)


class LidarRetina:
    def __init__(self):
        self.prev_theta = None        # world-aligned bins
        self.prev_t = None
        self.centres = (np.arange(SECTORS) + 0.5) * (2 * math.pi / SECTORS) - math.pi

    def ranges(self, xy_body):
        """Robust near range per body-frame sector."""
        d = np.full(SECTORS, RANGE_MAX)
        if len(xy_body):
            r = np.hypot(xy_body[:, 0], xy_body[:, 1])
            keep = (r >= RANGE_MIN) & (r < RANGE_MAX)
            az = np.arctan2(xy_body[keep, 1], xy_body[keep, 0])
            k = np.clip(((az + math.pi) / (2 * math.pi) * SECTORS).astype(int), 0, SECTORS - 1)
            rk = r[keep]
            for s in np.unique(k):
                d[s] = float(np.percentile(rk[k == s], 10))
        return d

    def step(self, xy_body, yaw, t):
        """xy_body: (N, 2) obstacle-band returns in the body frame; yaw: world heading (rad);
        t: source time (s). Returns (rates_by_type_side, features)."""
        d = self.ranges(xy_body)
        theta = 2.0 * np.arctan(OBJECT_W / (2.0 * d))
        theta[d >= RANGE_MAX] = 0.0
        shift = int(round(yaw / (2 * math.pi / SECTORS)))
        world_theta = np.roll(theta, shift)                 # bin k (body) -> bin k+shift (world)
        loom_body = np.zeros(SECTORS)
        dt = None
        if self.prev_theta is not None and t > self.prev_t:
            dt = t - self.prev_t
            if dt <= 0.5:                                   # a gap is not motion
                rate = np.clip((world_theta - self.prev_theta) / dt, 0.0, None)
                loom_body = np.roll(rate, -shift)
        self.prev_theta, self.prev_t = world_theta, t
        left = self.centres > 0
        feats = {}
        rates = {}
        for side, mask in (('left', left), ('right', ~left)):
            eye = EYE_OF_FIELD[side]
            lm = loom_body[mask]
            big = (theta[mask] >= math.radians(LPLC2_MIN_THETA_DEG))
            loom = float(lm.max()) if len(lm) else 0.0
            loom_big = float((lm * big).max()) if len(lm) else 0.0
            rates[('LC4', eye)] = min(MAX_RATE_HZ, LOOM_GAIN_HZ_PER_RAD_S * loom)
            rates[('LPLC2', eye)] = min(MAX_RATE_HZ, LOOM_GAIN_HZ_PER_RAD_S * loom_big)
            front = np.abs(self.centres) <= math.radians(FRONT_HALF_DEG)
            free = float(d[front & mask].min()) if (front & mask).any() else RANGE_MAX
            k = np.clip((free - LC9_FREE_ZERO_M) / (LC9_FREE_FULL_M - LC9_FREE_ZERO_M), 0.0, 1.0)
            rates[('LC9', eye)] = LC9_MAX_HZ * float(k)
            feats[side] = dict(loom_rad_s=round(loom, 4), loom_big_rad_s=round(loom_big, 4),
                               free_ahead_m=round(free, 3), nearest_m=round(float(d[mask].min()), 3))
        feats['dt_s'] = dt
        feats['ranges_m'] = [round(float(x), 2) for x in d]
        return rates, feats


def rates_vector(registry, rates):
    """Per-input-cell rates in registry order (all cells of a type and side share one rate)."""
    out = []
    for t in ('LC4', 'LPLC2', 'LC9'):
        for c in registry['inputs'][t]:
            out.append(rates.get((t, c['anatomical_side']), 0.0))
    return np.asarray(out, dtype=np.float32)


def input_indices(registry):
    return [c['model_index'] for t in ('LC4', 'LPLC2', 'LC9') for c in registry['inputs'][t]]


# ---------------------------------------------------------------------------------------------
# Version 2 (2026-10-10, after stage2_001): v1 failed the stage-2 gate (loom > 0.05 rad/s in
# 75 % of windows while the robot stood still; LC4 at its ceiling in 26 % of windows) because
# frame-to-frame jitter of the sector ranges read as expansion. v1 above is kept as recorded.
RETINA_V2 = dict(
    ema=0.5,                    # range smoothing per world-aligned bin
    baseline_s=0.30,            # expansion measured over this baseline ...
    baseline_min_s=0.20,        # ... at least this long
    approach_eps_m=0.005,       # the smoothed range must keep shrinking across the last two scans
    deadband_rad_s=0.05,
    reach_m=3.0,                # only sectors nearer than this can loom
    gain_hz_per_rad_s=400.0,
    gap_s=0.50,                 # a scan gap resets the history (no motion across gaps)
)


class LidarRetinaV2(LidarRetina):
    VERSION = 2

    def __init__(self):
        super().__init__()
        self.hist = []                # (t, world-aligned smoothed range)

    def step(self, xy_body, yaw, t):
        return self.step_ranges(self.ranges(xy_body), yaw, t)

    def step_ranges(self, d, yaw, t):
        c = RETINA_V2
        d = np.asarray(d, dtype=float)
        shift = int(round(yaw / (2 * math.pi / SECTORS)))
        dw = np.roll(d, shift)
        if self.hist and t - self.hist[-1][0] > c['gap_s']:
            self.hist = []
        if self.hist:
            dw = c['ema'] * dw + (1 - c['ema']) * self.hist[-1][1]
        self.hist.append((t, dw))
        self.hist = [h for h in self.hist if t - h[0] <= 1.0]
        loom_w = np.zeros(SECTORS)
        old = [h for h in self.hist if t - h[0] >= c['baseline_min_s']]
        if old and len(self.hist) >= 3:
            t0, d0 = min(old, key=lambda h: abs((t - h[0]) - c['baseline_s']))
            theta_now = 2.0 * np.arctan(OBJECT_W / (2.0 * dw))
            theta_then = 2.0 * np.arctan(OBJECT_W / (2.0 * d0))
            rate = (theta_now - theta_then) / (t - t0)
            shrinking = (self.hist[-1][1] < self.hist[-2][1] - c['approach_eps_m']) & \
                        (self.hist[-2][1] < self.hist[-3][1] - c['approach_eps_m'])
            ok = shrinking & (dw < c['reach_m'])
            loom_w = np.where(ok, np.clip(rate - c['deadband_rad_s'], 0.0, None), 0.0)
        loom_body = np.roll(loom_w, -shift)
        d_body = np.roll(dw, -shift)
        theta = 2.0 * np.arctan(OBJECT_W / (2.0 * d_body))
        left = self.centres > 0
        rates, feats = {}, {}
        for side, mask in (('left', left), ('right', ~left)):
            eye = EYE_OF_FIELD[side]
            lm = loom_body[mask]
            big = theta[mask] >= math.radians(LPLC2_MIN_THETA_DEG)
            loom = float(lm.max())
            loom_big = float((lm * big).max())
            rates[('LC4', eye)] = min(MAX_RATE_HZ, c['gain_hz_per_rad_s'] * loom)
            rates[('LPLC2', eye)] = min(MAX_RATE_HZ, c['gain_hz_per_rad_s'] * loom_big)
            front = np.abs(self.centres) <= math.radians(FRONT_HALF_DEG)
            free = float(d[front & mask].min()) if (front & mask).any() else RANGE_MAX
            k = np.clip((free - LC9_FREE_ZERO_M) / (LC9_FREE_FULL_M - LC9_FREE_ZERO_M), 0.0, 1.0)
            rates[('LC9', eye)] = LC9_MAX_HZ * float(k)
            feats[side] = dict(loom_rad_s=round(loom, 4), loom_big_rad_s=round(loom_big, 4),
                               free_ahead_m=round(free, 3), nearest_m=round(float(d[mask].min()), 3))
        feats['ranges_m'] = [round(float(x), 2) for x in d]
        feats['retina_version'] = 2
        return rates, feats


STALE_SCAN_S = 0.30               # consumers zero all loom inputs when the newest scan is older


def stale_rates(rates):
    """Inputs for a window whose newest scan is stale: no loom, no forward drive."""
    return {k: 0.0 for k in rates}


# ---------------------------------------------------------------------------------------------
# Version 3 (2026-10-10, after retina_eval of v2 on stage2_001): v2 still showed loom in 23 % of
# still scans and 50 % of turn-in-place scans. Causes: the L1's non-repetitive scan pattern
# samples different directions every scan, and rolling whole body sectors by the rounded yaw
# misaligns them while turning. v3 pools the last POOL_S of returns in WORLD coordinates and bins
# them by world direction from the current position; v2's smoothing/approach/deadband follow.
POOL_S = 0.30
RETINA_V3 = dict(RETINA_V2, deadband_rad_s=0.12)   # retina_sweep on stage2_002: still 4.0 %, near 21.5 %


class LidarRetinaV3(LidarRetinaV2):
    VERSION = 3

    def __init__(self):
        super().__init__()
        self.pool = []                # (t, world xy)

    def step(self, xy_body, yaw, t, robot_xy):
        c, s = math.cos(yaw), math.sin(yaw)
        world = np.c_[robot_xy[0] + xy_body[:, 0] * c - xy_body[:, 1] * s,
                      robot_xy[1] + xy_body[:, 0] * s + xy_body[:, 1] * c] if len(xy_body) else np.zeros((0, 2))
        if self.pool and t - self.pool[-1][0] > RETINA_V2['gap_s']:
            self.pool = []
        self.pool.append((t, world))
        self.pool = [p for p in self.pool if t - p[0] <= POOL_S]
        pts = np.vstack([p[1] for p in self.pool]) - np.asarray(robot_xy)
        # world-direction bins: rotate into the body frame for ranges(), then roll by an exact
        # bin count is no longer needed -- bin directly in the world frame and keep yaw only for
        # the left/right field assignment.
        d_world = self.ranges(pts)                                   # bins by world azimuth
        return self.step_world(d_world, yaw, t)

    def step_world(self, dw_raw, yaw, t):
        c = RETINA_V3
        dw = np.asarray(dw_raw, dtype=float)
        if self.hist and t - self.hist[-1][0] > c['gap_s']:
            self.hist = []
        if self.hist:
            dw = c['ema'] * dw + (1 - c['ema']) * self.hist[-1][1]
        self.hist.append((t, dw))
        self.hist = [h for h in self.hist if t - h[0] <= 1.0]
        loom_w = np.zeros(SECTORS)
        old = [h for h in self.hist if t - h[0] >= c['baseline_min_s']]
        if old and len(self.hist) >= 3:
            t0, d0 = min(old, key=lambda h: abs((t - h[0]) - c['baseline_s']))
            rate = (2.0 * np.arctan(OBJECT_W / (2.0 * dw)) - 2.0 * np.arctan(OBJECT_W / (2.0 * d0))) / (t - t0)
            shrinking = (self.hist[-1][1] < self.hist[-2][1] - c['approach_eps_m']) & \
                        (self.hist[-2][1] < self.hist[-3][1] - c['approach_eps_m'])
            loom_w = np.where(shrinking & (dw < c['reach_m']), np.clip(rate - c['deadband_rad_s'], 0.0, None), 0.0)
        body_az = np.remainder(self.centres - yaw + math.pi, 2 * math.pi) - math.pi   # world bin centre -> body azimuth
        theta = 2.0 * np.arctan(OBJECT_W / (2.0 * dw))
        rates, feats = {}, {}
        for side, mask in (('left', body_az > 0), ('right', body_az <= 0)):
            eye = EYE_OF_FIELD[side]
            lm, big = loom_w[mask], theta[mask] >= math.radians(LPLC2_MIN_THETA_DEG)
            loom, loom_big = (float(lm.max()), float((lm * big).max())) if len(lm) else (0.0, 0.0)
            rates[('LC4', eye)] = min(MAX_RATE_HZ, c['gain_hz_per_rad_s'] * loom)
            rates[('LPLC2', eye)] = min(MAX_RATE_HZ, c['gain_hz_per_rad_s'] * loom_big)
            front = mask & (np.abs(body_az) <= math.radians(FRONT_HALF_DEG))
            free = float(dw[front].min()) if front.any() else RANGE_MAX
            k = np.clip((free - LC9_FREE_ZERO_M) / (LC9_FREE_FULL_M - LC9_FREE_ZERO_M), 0.0, 1.0)
            rates[('LC9', eye)] = LC9_MAX_HZ * float(k)
            feats[side] = dict(loom_rad_s=round(loom, 4), loom_big_rad_s=round(loom_big, 4),
                               free_ahead_m=round(free, 3), nearest_m=round(float(dw[mask].min()) if len(lm) else RANGE_MAX, 3))
        feats['world_ranges_m'] = [round(float(x), 2) for x in dw_raw]
        feats['retina_version'] = 3
        return rates, feats
