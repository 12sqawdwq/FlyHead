"""Stage 2 pass A: recorded session -> SLAM -> LiDAR retina, one row per scan (SLAM venv).
python stage2_retina.py RUN_DIR START_OFFSET_S DURATION_S OUT_DIR
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / 'vendor_slam'))          # copy of the deployed SLAM server modules
import rawlog  # noqa: E402
import reloc as RL  # noqa: E402
import slam as SL  # noqa: E402
from retina import LidarRetina, LidarRetinaV3  # noqa: E402

DEPLOY = Path('<SERVER_ROOT>/slam/deployments/distributed_control')
run, start_off, duration, out = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=False)
reg = json.loads((ROOT / 'config/loom_registry.json').read_text())

events = []
for line in open(run / 'navigation.jsonl'):
    try:
        r = json.loads(line)
    except ValueError:
        continue
    if (r.get('text') or '').startswith('Posture change detected: '):
        events.append((r['t'], 'stand' if 'stand' in r['text'].split(':')[1][:8] else 'crouch'))
mode_at = lambda w: ([k for t, k in events if w >= t] or ['crouch'])[-1]
LIDAR_H = {'stand': 0.30, 'crouch': 0.21}

base = RL.BaseMap(RL.load_points(DEPLOY / 'maps/onboard_20260926_manual_cleanup_20261005/map.ply'))
engine = SL.SlamEngine(out / 'slam_tmp', base=base)
captured = {}
orig_register = engine.kiss.register_frame
def register(frame, tn):
    captured['frame'] = frame
    return orig_register(frame, tn)
engine.kiss.register_frame = register

retina = LidarRetina()            # v1, as recorded in stage2_001
retina3 = LidarRetinaV3()
rows, retina_rows = [], []
latest = None                       # (rates, feats, pose, t)
first_wall = next_window = None
t0 = time.perf_counter()
log = open(out / 'retina.jsonl', 'w')
for wall, kind, payload in rawlog.read_records(run / 'raw.xt'):
    first_wall = first_wall or wall
    if wall > first_wall + start_off + duration:
        break
    engine.mode = mode_at(wall)
    if kind == rawlog.IMU:
        engine.add_imu([rawlog.decode_imu(payload)])
        continue
    if kind != rawlog.CLOUD:
        continue
    stamp, pts = rawlog.decode_cloud(payload)
    before = engine.frames
    captured.pop('frame', None)
    engine.add_cloud(stamp, pts.astype(np.float32))
    if not engine.attached:
        for _ in range(40):
            if engine.attached or engine.pending_Toff is not None:
                break
            time.sleep(0.1)
        continue
    if engine.frames == before or 'frame' not in captured or not engine.traj:
        continue
    W = engine.Toff @ engine.gravity @ engine.kiss.last_pose
    Wb = W @ engine.body_T
    world = captured['frame'] @ W[:3, :3].T + W[:3, 3]
    st, x, y, z, yaw = engine.traj[-1]
    floor = z - LIDAR_H[engine.mode]
    band = world[(world[:, 2] > floor + 0.08) & (world[:, 2] < floor + 0.50)]
    body = (band - Wb[:3, 3]) @ Wb[:3, :3]                     # world -> body (x forward, y left)
    rates, feats = retina.step(body[:, :2], yaw, wall)
    rates3, feats3 = retina3.step(body[:, :2], yaw, wall, (float(Wb[0, 3]), float(Wb[1, 3])))
    if wall < first_wall + start_off:
        continue
    row = dict(t=round(wall - first_wall, 3), pose=[round(x, 3), round(y, 3), round(yaw, 4)], fit=engine.fitness,
               mode=engine.mode, rates={'%s_%s' % k: round(v, 2) for k, v in rates.items()}, features=feats,
               rates_v3={'%s_%s' % k: round(v, 2) for k, v in rates3.items()}, features_v3=feats3)
    log.write(json.dumps(row) + chr(10)); rows.append(row)
    if len(rows) % 500 == 0:
        log.flush(); print('t %.0f s scans %d fit %.2f' % (row['t'], len(rows), row['fit'] or 0), flush=True)
engine.close()
log.close()
print('done: %d scans in %.0f s wall' % (len(rows), time.perf_counter() - t0))
