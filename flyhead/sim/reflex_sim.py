"""Stage 6: closed-loop simulation of planner + fly reflexes (brain mode 'reflex'), real time.

The SLAM server's own Navigator (planner, live obstacle layer, stop rule, pursuit) and BrainLink
run unchanged; a live brain service (brain_service.py, separate port) supplies the decoded windows.
Each 100 ms: ray-cast scan of the map + a person -> Navigator.feed and BrainLink.on_scan ->
Navigator.control -> (reflex mode) BrainLink.command takes over on FREEZE / ESCAPE_PROGRAM ->
plant (first-order lag, acceleration limit, standing speed gain, turning about the turning point).

Run in the server environment with a brain service on XT_BRAIN_PORT (scripts/start_brain_service.sh):
XT_BRAIN_ENABLED=1 python -m flyhead.sim.reflex_sim MAP_PKG ARM SEED OUT.jsonl     (ARM: reflex | planner)
MAP_PKG may be 'synthetic' for the arena from flyhead.sim.synthetic_map.
"""
import json
import math
import os
import sys
import tempfile
import time
import types

import numpy as np

if len(sys.argv) != 5:
    sys.exit(__doc__)
PKG, ARM, SEED, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
os.environ.setdefault('XT_BRAIN_ENABLED', '1')
if PKG == 'synthetic':
    from flyhead.sim.synthetic_map import write
    PKG = str(write(tempfile.mkdtemp(prefix='flyhead_arena_')))
from flyhead.navigation import nav as NV  # noqa: E402
from flyhead.server.brain_link import BrainLink  # noqa: E402

DT, TAU_S, ACCEL, GAIN = 0.1, 0.25, 0.8, 1.34
LIDAR_H = 0.31
TP_IN_LIDAR = np.array(NV.REFERENCE_BODY[:2])      # turning point in the LiDAR frame
START = (7.0, -1.1, 0.0)                            # open area (stage 3 roam_open)
SECONDS = 180.0
PERSON_AT_S, PERSON_AHEAD_M, PERSON_V, PERSON_R, STOP_AT_M = 8.0, 3.0, 0.5, 0.25, 0.7
BODY_R = 0.35

rng = np.random.default_rng(SEED)
navigator = NV.Navigator(PKG, tempfile.mkdtemp(prefix='sim_reflex_'))
wall = navigator.nm.blocked_for(0.45)
angles = np.linspace(-math.pi, math.pi, 720, endpoint=False)
steps = np.arange(0.15, 8.0, 0.025)


def lidar_pose(x, y, yaw):
    """Turning point (x, y) -> LiDAR position."""
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([x - (c * TP_IN_LIDAR[0] - s * TP_IN_LIDAR[1]), y - (s * TP_IN_LIDAR[0] + c * TP_IN_LIDAR[1])])


def scan(origin, person):
    d = np.c_[np.cos(angles), np.sin(angles)]
    pts = origin[None, None, :] + d[:, None, :] * steps[None, :, None]
    ij = np.floor((pts - navigator.nm.origin) / navigator.nm.res).astype(int)
    ok = (ij[..., 0] >= 0) & (ij[..., 0] < wall.shape[0]) & (ij[..., 1] >= 0) & (ij[..., 1] < wall.shape[1])
    hit = np.zeros(ok.shape, bool)
    hit[ok] = wall[ij[..., 0][ok], ij[..., 1][ok]]
    if person is not None:
        hit |= np.hypot(pts[..., 0] - person[0], pts[..., 1] - person[1]) <= PERSON_R
    first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
    rays = np.flatnonzero(first >= 0)
    xy = pts[rays, first[rays]] + rng.normal(0, 0.01, (len(rays), 2))
    floor = navigator.nm.floor_at(xy)
    floor = np.where(np.isfinite(floor), floor, 0.0)
    world = np.vstack([np.c_[xy, floor + h] for h in (0.12, 0.25, 0.40)])
    return world


def clearance(x, y, person):
    i, j = navigator.nm.to_ij(np.array([x, y]))
    r = int(1.5 / navigator.nm.res)
    win = wall[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]
    cells = np.argwhere(win)
    d = 1.5
    if len(cells):
        cxy = navigator.nm.to_xy(cells + [max(0, i - r), max(0, j - r)])
        d = float(np.min(np.hypot(cxy[:, 0] - x, cxy[:, 1] - y)))
    dp = math.inf if person is None else math.hypot(person[0] - x, person[1] - y) - PERSON_R
    return d, dp


def feed(x, y, yaw, person):
    lid = lidar_pose(x, y, yaw)
    floor = navigator.nm.floor_at(lid[None])[0]
    floor = float(floor) if np.isfinite(floor) else 0.0
    c, s = math.cos(yaw), math.sin(yaw)
    Wb = np.eye(4)
    Wb[:2, :2] = [[c, -s], [s, c]]
    Wb[:3, 3] = [lid[0], lid[1], floor + LIDAR_H]
    world = scan(lid, person)
    now = time.time()
    navigator.feed(Wb, Wb[:3, 3].copy(), world, 0.98, received_at=now, source_stamp=now - 0.05)
    session.nav = navigator
    brain.on_scan(navigator, world, Wb[:3, 3].copy())


session = types.SimpleNamespace(nav=navigator)
brain = BrainLink(session)
x, y, yaw = START
v = w = 0.0
person = None
person_v = None
feed(x, y, yaw, None)
time.sleep(2.0)
for _ in range(30):                                   # obstacle layer + brain windows warm up
    feed(x, y, yaw, None); time.sleep(DT)
navigator.hardware_stand = True
goal, why = navigator.pick_explore_goal(6.0, 10.0)
assert goal is not None, why
navigator.set_goal(*goal)
navigator.v_max = 0.30
ok, why = navigator.start()
assert ok, why
brain.set_mode('reflex' if ARM == 'reflex' else 'shadow')
out = open(OUT, 'w')
out.write(json.dumps(dict(type='setup', arm=ARM, seed=SEED, start=START, goal=goal)) + '\n')
t0 = time.time()
deadline = t0
result = 'timeout'
while True:
    deadline += DT
    time.sleep(max(0.0, deadline - time.time()))
    t = time.time() - t0
    if t > SECONDS:
        break
    # person: appears PERSON_AHEAD_M ahead on the route and walks toward the robot, stops at STOP_AT_M
    if person is None and t >= PERSON_AT_S and navigator.route is not None:
        p = navigator.route.point_at(min(navigator.route.length, navigator.progress + PERSON_AHEAD_M))
        person = [float(p[0]), float(p[1])]
        d = np.array([x, y]) - p
        person_v = d / max(1e-6, np.linalg.norm(d)) * PERSON_V
    if person is not None and person_v is not None:
        if math.hypot(person[0] - x, person[1] - y) - PERSON_R <= STOP_AT_M:
            person_v = None
        else:
            person[0] += person_v[0] * DT; person[1] += person_v[1] * DT
    feed(x, y, yaw, person)
    vw = navigator.control(slam_ok=True, chassis_ok=True) if navigator.active else None
    cmd = (0.0, 0.0) if vw is None else vw
    source = 'planner'
    bv, bw, rec = brain.command(time.time())
    if brain.mode == 'reflex' and rec.get('takeover') and navigator.active:
        if not navigator.reflex_engaged:
            navigator.add_keepout(brain.threat_xy)          # as server.py
        navigator.reflex_hold(rec.get('state'))
        cmd, source = (bv, bw), 'reflex'
    # plant
    a = DT / TAU_S
    v += float(np.clip((cmd[0] * GAIN - v) * a, -ACCEL * DT, ACCEL * DT))
    w += (cmd[1] - w) * a
    yaw = math.remainder(yaw + w * DT, 2 * math.pi)
    x += v * math.cos(yaw) * DT; y += v * math.sin(yaw) * DT
    dw, dp = clearance(x, y, person)
    out.write(json.dumps(dict(t=round(t, 2), x=round(x, 3), y=round(y, 3), yaw=round(yaw, 3), v=round(v, 3), w=round(w, 3),
                              cmd=[round(cmd[0], 3), round(cmd[1], 3)], source=source, nav_state=navigator.state,
                              nav_reason=navigator.reason, active=navigator.active, brain_state=rec.get('state'),
                              takeover=bool(rec.get('takeover')), withheld=rec.get('withheld'), wall_m=round(dw, 3),
                              person_m=None if dp == math.inf else round(dp, 3), person=person,
                              contact=dw < BODY_R or dp < BODY_R, reflex_count=navigator.reflex_count)) + '\n')
    if not navigator.active:
        result = navigator.state + ': ' + (navigator.reason or '')
        if t > PERSON_AT_S + 1:
            break
out.write(json.dumps(dict(type='end', result=result, t=round(time.time() - t0, 1))) + '\n')
out.close()
print(ARM, SEED, result)
