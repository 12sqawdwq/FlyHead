#!/usr/bin/env python3
"""Per-frame posture evidence from a recorded session (base continuation).

Prints a time series of LiDAR height above the map floor, LiDAR tilt from the
IMU gravity vector, pitch/roll of the SLAM pose, map agreement, and the robot
mode reported by chassis telemetry (when the driver ran).  Used to calibrate
crouch/stand thresholds and to measure how the geometry changes.

  venv/bin/python server/posture_scan.py runs/<id>/raw.xt maps/<nav_pkg>
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np

from flyhead.navigation import nav as NV
from flyhead.slam import reloc as RL
from flyhead.slam import lidar_slam as S


def main(raw, pkg):
    nm = NV.NavMap(pkg)
    base = RL.BaseMap(RL.load_points(Path(pkg) / 'map.ply'))
    e = S.SlamEngine(Path('/tmp/xt_posture'), base=base)
    rows = []

    def on_frame(Wb, sensor, world, fit):
        f = nm.floor_at(sensor[None, :2])[0]
        R = Wb[:3, :3]
        pitch = math.degrees(math.asin(max(-1, min(1, -R[2, 0]))))
        roll = math.degrees(math.atan2(R[2, 1], R[2, 2]))
        rows.append(dict(stamp=e.traj[-1][0] if e.traj else None, x=float(sensor[0]), y=float(sensor[1]),
                         z=float(sensor[2]), lidar_h=float(sensor[2] - f) if np.isfinite(f) else None,
                         pitch=pitch, roll=roll, fit=fit))
    e.on_frame = on_frame
    imus, tilt, modes = [], [], []
    w0 = None
    with open(raw, 'rb') as fh:
        while True:
            h = fh.read(15)
            if len(h) < 15:
                break
            wall, = struct.unpack('<d', h[:8])
            kind, n = struct.unpack('<BI', h[10:15])
            p = fh.read(n)
            if len(p) < n:
                break
            w0 = w0 if w0 is not None else wall
            if kind == 2:
                v = struct.unpack('<d10f', p)
                imus.append(v)
                a = np.array(v[8:11])
                tilt.append((v[0], math.degrees(math.acos(max(-1, min(1, a[2] / np.linalg.norm(a)))))))
                if len(imus) >= 25:
                    e.add_imu(imus)
                    imus = []
            elif kind == 3:
                d = json.loads(p)
                if d.get('event') == 'status' and d.get('body'):
                    modes.append((d['t'], d['body'].get('robot_mode')))
            elif kind == 1:
                st, m = struct.unpack('<dI', p[:12])
                e.add_cloud(st, np.frombuffer(p, '<f4', offset=12, count=m * 5).reshape(m, 5))
                if not e.attached:
                    time.sleep(0.12)
    e.close()
    tilt = np.array(tilt)
    t0 = rows[0]['stamp'] if rows else 0
    print('frames', len(rows), 'self-mask voxels', {k: len(m.mask) for k, m in e.self_masks.items()})
    print('%7s %7s %7s %7s %7s %7s %6s %5s' % ('t[s]', 'z', 'lidar_h', 'tilt°', 'pitch°', 'roll°', 'fit', 'mode'))
    step = max(1, len(rows) // 60)
    for r in rows[::step]:
        tt = np.interp(r['stamp'], tilt[:, 0], tilt[:, 1]) if len(tilt) else float('nan')
        md = [m for t, m in modes if t <= r['stamp']]
        print('%7.1f %7.3f %7s %7.1f %7.1f %7.1f %6s %5s' % (
            r['stamp'] - t0, r['z'], '%.3f' % r['lidar_h'] if r['lidar_h'] is not None else '-', tt,
            r['pitch'], r['roll'], '%.2f' % r['fit'] if r['fit'] is not None else '-', md[-1] if md else '-'))
    json.dump(rows, open('/tmp/xt_posture_rows.json', 'w'))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
