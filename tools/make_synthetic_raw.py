"""Write a synthetic raw.xt session (LiDAR clouds + IMU + status) for testing the control server
without a robot: python -m flyhead.server.app --replay OUT.xt

The robot stands still for 3 s (SLAM seed frame and IMU levelling), then drives through the
synthetic arena (flyhead.sim.synthetic_map) at 0.2 m/s with a gentle turn. Clouds are ray-cast
in the LiDAR frame (360 deg x -5..+55 deg, walls 1.5 m high, floor), 10 Hz, per-point time
offsets; IMU at 200 Hz (yaw quaternion, gyro z, gravity +z). Not a sensor model: it only feeds
the pipeline. python tools/make_synthetic_raw.py OUT.xt [SECONDS]
"""
import json
import math
import struct
import sys

import numpy as np

from flyhead.slam import rawlog
from flyhead.sim import synthetic_map as SM

LIDAR_H = 0.45
WALL_TOP = SM.WALL_TOP
START = (7.0, -1.1, 0.0)


def main(out, seconds=20.0):
    grid = SM.build() == 0
    res, ox, oy = SM.RES, SM.ORIGIN[0], SM.ORIGIN[1]
    az = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    el = np.radians(np.linspace(-5, 55, 16))
    steps = np.arange(0.2, 12.0, 0.02)
    rng = np.random.default_rng(1)
    t0 = 1.0e9
    x, y, yaw = START
    records = []

    def rec(t, kind, payload):
        records.append(rawlog.RECORD_HEADER.pack(t, b'XT', kind, len(payload)) + payload)

    for k in range(int(seconds * 200)):
        t = k / 200.0
        moving = t >= 3.0
        v, w = (0.2, 0.06) if moving else (0.0, 0.0)
        x += v * math.cos(yaw) / 200; y += v * math.sin(yaw) / 200; yaw += w / 200
        q = (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))
        rec(t0 + t, rawlog.IMU, struct.pack('<d10f', t0 + t, *q, 0.0, 0.0, w, 0.0, 0.0, 9.81))
        if k % 20 == 0:                                 # 10 Hz cloud
            d = np.c_[np.cos(az + yaw), np.sin(az + yaw)]
            pts = np.array([x, y]) + d[:, None, :] * steps[None, :, None]
            ij = np.floor((pts - [ox, oy]) / res).astype(int)
            ok = (ij[..., 0] >= 0) & (ij[..., 0] < grid.shape[0]) & (ij[..., 1] >= 0) & (ij[..., 1] < grid.shape[1])
            hit = np.zeros(ok.shape, bool)
            hit[ok] = grid[ij[..., 0][ok], ij[..., 1][ok]]
            first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
            cloud = []
            for e in el:
                for i, a in enumerate(az):
                    r_wall = steps[first[i]] if first[i] >= 0 else None
                    r_floor = LIDAR_H / math.tan(-e) if e < 0 else None
                    r = None
                    if r_floor is not None and (r_wall is None or r_floor < r_wall):
                        r = r_floor
                    elif r_wall is not None and LIDAR_H + r_wall * math.tan(e) < WALL_TOP:
                        r = r_wall
                    if r is None or r > 11.0:
                        continue
                    r += rng.normal(0, 0.01)
                    cloud.append((r * math.cos(e) * math.cos(a), r * math.cos(e) * math.sin(a), r * math.sin(e),
                                  100.0, (i / len(az)) * 0.1))
            c = np.asarray(cloud, '<f4')
            rec(t0 + t, rawlog.CLOUD, struct.pack('<dI', t0 + t, len(c)) + c.tobytes())
        if k % 100 == 0:
            rec(t0 + t, rawlog.JSON, json.dumps(dict(event='status', t=t0 + t, synthetic=True,
                                                     chassis_running=False, lidar_h=LIDAR_H)).encode())
    with open(out, 'wb') as f:
        f.writelines(records)
    print('wrote', out, len(records), 'records,', seconds, 's')


if __name__ == '__main__':
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 20.0)
