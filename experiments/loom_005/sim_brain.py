"""Stage 3: closed-loop simulation, brain in the loop. No planner, no route, no constant drive.

Kinematics as in the SLAM project's sim2: unicycle about the turning point, first-order command
lag TAU_S, physical acceleration limit, standing speed gain. Scans are 2-D ray casts on the
navigation map's obstacle grid (plus scenario objects, which may move). Each 100 ms:
scan -> body-frame points -> LidarRetina -> Brain window -> decoder -> envelope -> plant.
A 'blind' arm replaces brain+decoder by a constant forward command (baseline only).

python sim_brain.py SCENARIO ARM SECONDS OUT.jsonl   (ARM: brain | blind | blind_raw)
"""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(1, str(ROOT / 'vendor_slam'))
import navmap  # noqa: E402
from decoder import DecoderV2, DecoderV3, DecoderV4, DecoderV5, DecoderV6, DecoderV7, DecoderV8, DecoderV9, decode  # noqa: E402
from envelope import BODY_R, limit  # noqa: E402
from retina import LidarRetinaV3, input_indices, rates_vector  # noqa: E402

PKG = Path('<SERVER_ROOT>/slam/deployments/distributed_control/maps/onboard_20260926_manual_cleanup_20261005')
DT = 0.1
TAU_S = 0.25
ACCEL = 0.8
GAIN = 1.25
LIDAR_AHEAD = 0.11

# scenarios: start pose, objects [(x, y, r, vx, vy, t_start)]
SCENARIOS = {
    # lane (2.6, 4.6) -> (11.3, 7.8), 1.68 m clearance at the start: drive toward the lane's far end wall
    'wall_ahead': dict(start=(5.6, 6.45, math.radians(20)), objects=[]),
    # open area around (7.0, -1.1), 2.09 m clearance: free roaming
    'roam_open': dict(start=(7.0, -1.1, math.radians(40)), objects=[]),
    # stage3_001 objects (0.6 m/s, never stop) -- kept as recorded
    'loom_front': dict(start=(7.0, -1.1, 0.0), objects=[(9.6, -1.1, 0.25, -0.6, 0.0, 1.0)]),
    'loom_left': dict(start=(7.0, -1.1, 0.0), objects=[(7.6, 1.0, 0.25, 0.0, -0.6, 1.0)]),
    'loom_right': dict(start=(7.0, -1.1, 0.0), objects=[(7.6, -3.2, 0.25, 0.0, 0.6, 1.0)]),
    # stage3_002: person-like approach, 0.5 m/s, stops for good STOP_AT_M from the robot
    'person_front': dict(start=(7.0, -1.1, 0.0), objects=[(9.8, -1.1, 0.25, -0.5, 0.0, 1.0)], stop_at=0.7),
    'person_left': dict(start=(7.0, -1.1, 0.0), objects=[(7.6, 1.1, 0.25, 0.0, -0.5, 1.0)], stop_at=0.7),
    'person_right': dict(start=(7.0, -1.1, 0.0), objects=[(7.6, -3.3, 0.25, 0.0, 0.5, 1.0)], stop_at=0.7),
}


class World:
    def __init__(self, objects):
        self.nm = navmap.NavMap(str(PKG))
        self.wall = self.nm.blocked_for(0.32)
        self.objects = [list(o) for o in objects]
        self.angles = np.linspace(-math.pi, math.pi, 720, endpoint=False)
        self.steps = np.arange(0.3, 8.0, 0.025)

    def scan(self, origin, t):
        d = np.c_[np.cos(self.angles), np.sin(self.angles)]
        pts = origin[None, None, :] + d[:, None, :] * self.steps[None, :, None]
        ij = np.floor((pts - self.nm.origin) / self.nm.res).astype(int)
        ok = (ij[..., 0] >= 0) & (ij[..., 0] < self.wall.shape[0]) & (ij[..., 1] >= 0) & (ij[..., 1] < self.wall.shape[1])
        hit = np.zeros(ok.shape, bool)
        hit[ok] = self.wall[ij[..., 0][ok], ij[..., 1][ok]]
        for x, y, r, vx, vy, ts in self.objects:
            if t >= ts:
                hit |= np.hypot(pts[..., 0] - x, pts[..., 1] - y) <= r
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
        rays = np.flatnonzero(first >= 0)
        return pts[rays, first[rays]]

    def move(self, t, robot_xy=None, stop_at=None):
        for o in self.objects:
            if t >= o[5]:
                if stop_at is not None and robot_xy is not None and math.hypot(o[0] - robot_xy[0], o[1] - robot_xy[1]) - o[2] <= stop_at:
                    o[3] = o[4] = 0.0                      # the person stops for good
                o[0] += o[3] * DT; o[1] += o[4] * DT

    def clearance(self, xy, t):
        """True distance from the turning point to the nearest wall cell or object surface."""
        i, j = self.nm.to_ij(np.asarray(xy))
        r = int(1.5 / self.nm.res)
        win = self.wall[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]
        cells = np.argwhere(win)
        d = 1.5
        if len(cells):
            cxy = self.nm.to_xy(cells + [max(0, i - r), max(0, j - r)])
            d = float(np.min(np.hypot(cxy[:, 0] - xy[0], cxy[:, 1] - xy[1])))
        for x, y, rr, _, _, ts in self.objects:
            if t >= ts:
                d = min(d, math.hypot(x - xy[0], y - xy[1]) - rr)
        return d


def main(name, arm, seconds, out_path):
    sc = SCENARIOS[name]
    world = World(sc['objects'])
    x, y, yaw = sc['start']
    v = w = 0.0
    retina = LidarRetinaV3()
    decoder = {'2': DecoderV2, '3': DecoderV3, '4': DecoderV4, '5': DecoderV5, '6': DecoderV6, '7': DecoderV7, '8': DecoderV8, '9': DecoderV9}.get(os.environ.get('LOOM_DECODER', ''), lambda: None)()
    brain = None
    if arm == 'brain':
        from brain import Brain
        reg = json.loads((ROOT / 'config/loom_registry.json').read_text())
        brain = Brain(reg, input_indices(reg), ROOT / 'cache')
    out = open(out_path, 'w')
    t = 0.0
    while t < seconds:
        lid = np.array([x + LIDAR_AHEAD * math.cos(yaw), y + LIDAR_AHEAD * math.sin(yaw)])
        pts = world.scan(lid, t)
        c, s = math.cos(yaw), math.sin(yaw)
        rel = pts - [x, y]
        body = np.c_[rel[:, 0] * c + rel[:, 1] * s, -rel[:, 0] * s + rel[:, 1] * c]
        rates, feats = retina.step(body, yaw, t, (x, y))
        if brain is not None:
            delta, all_spikes, ms = brain.step(rates_vector(reg, rates))
            hz = {k: n / brain.window_s for k, n in brain.readouts_by_type(delta).items()}
            intent = decoder.decode(hz, t) if decoder else decode(hz)
        else:
            hz, all_spikes, ms = {}, 0, 0.0
            intent = dict(state='BLIND', v=0.15, w=0.0)
        if arm == 'blind_raw':                      # baseline only: no envelope
            v_cmd, w_cmd, why = intent['v'], intent['w'], None
        else:
            v_cmd, w_cmd, why = limit(body, intent['v'], intent['w'])
        a = DT / TAU_S
        dv = (v_cmd * GAIN - v) * a
        v += float(np.clip(dv, -ACCEL * DT, ACCEL * DT))
        w += (w_cmd - w) * a
        yaw = math.remainder(yaw + w * DT, 2 * math.pi)
        x += v * math.cos(yaw) * DT; y += v * math.sin(yaw) * DT
        world.move(t, (x, y), sc.get('stop_at'))
        clear = world.clearance((x, y), t)
        out.write(json.dumps(dict(t=round(t, 1), x=round(x, 3), y=round(y, 3), yaw=round(yaw, 3), v=round(v, 3), w=round(w, 3),
                                  clearance=round(clear, 3), contact=clear < BODY_R, intent=intent, executed=[round(v_cmd, 3), round(w_cmd, 3)],
                                  envelope=why, inputs={'%s_%s' % k: round(val, 1) for k, val in rates.items() if val},
                                  readouts={'%s_%s' % k: round(val, 1) for k, val in hz.items() if val},
                                  loom=[feats['left']['loom_rad_s'], feats['right']['loom_rad_s']], brain_ms=round(ms, 1),
                                  objects=[[round(o[0], 3), round(o[1], 3)] for o in world.objects])) + '\n')
        t += DT
    out.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4])
