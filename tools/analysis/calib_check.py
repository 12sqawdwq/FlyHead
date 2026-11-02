#!/usr/bin/env python3
"""Check IMU<->LiDAR yaw agreement and the LiDAR forward direction from a drive.

Runs pure LiDAR odometry (no IMU prior, no deskew) and compares per-window yaw
change with the IMU orientation (both about gravity); then, while a
forward-only command is active, measures the motion direction in the LiDAR
frame (angle from LiDAR +x).

  venv/bin/python server/calib_check.py runs/<id>/raw.xt
"""
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

from flyhead.slam import lidar_slam as S


def main(raw):
    S.IMU_PRIOR = False
    S.IMU_DESKEW = False
    e = S.SlamEngine(Path('/tmp/xt_calib'))
    imus, cmds, w0 = [], [], None
    allimu = []
    with open(raw, 'rb') as f:
        while True:
            h = f.read(15)
            if len(h) < 15:
                break
            wall, = struct.unpack('<d', h[:8])
            kind, n = struct.unpack('<BI', h[10:15])
            p = f.read(n)
            if len(p) < n:
                break
            w0 = w0 if w0 is not None else wall
            if kind == 2:
                v = struct.unpack('<d10f', p)
                imus.append(v)
                allimu.append(v)
                if len(imus) >= 25:
                    e.add_imu(imus)
                    imus = []
            elif kind == 3:
                d = json.loads(p)
                if d.get('event') == 'status' and d.get('cmd') is not None:
                    cmds.append((d['t'], d['cmd'][0], d['cmd'][1], wall - w0))
            elif kind == 1:
                st, m = struct.unpack('<dI', p[:12])
                e.add_cloud(st, np.frombuffer(p, '<f4', offset=12, count=m * 5).reshape(m, 5))
    traj = np.array([t for t in e.traj])          # stamp, x, y, z, yaw (levelled lidar)
    imu = np.array(allimu)
    G = e.gravity[:3, :3]
    # IMU yaw about gravity: heading of the IMU x axis after levelling
    R = S.quat_to_rot(imu[:, 1:5])
    R0inv = R[0].T
    # express orientation relative to the first sample, in the levelled frame
    xs = np.einsum('ij,njk,k->ni', G, np.einsum('ij,njk->nik', R0inv, R), np.array([1.0, 0, 0]))
    imu_yaw = np.unwrap(np.arctan2(xs[:, 1], xs[:, 0]))
    lid_yaw = np.unwrap(traj[:, 4])
    iy = np.interp(traj[:, 0], imu[:, 0], imu_yaw)
    # compare increments over 1 s windows where rotation is significant
    k = 4
    dl = lid_yaw[k:] - lid_yaw[:-k]
    di = iy[k:] - iy[:-k]
    sel = np.abs(dl) > 0.15
    out = dict(frames=len(traj), turn_windows=int(sel.sum()))
    if sel.any():
        corr = float(np.corrcoef(dl[sel], di[sel])[0, 1])
        gain = float(np.sum(dl[sel] * di[sel]) / np.sum(di[sel] ** 2))
        out.update(yaw_corr=round(corr, 3), lidar_over_imu_gain=round(gain, 3),
                   total_turn_lidar_deg=round(math.degrees(lid_yaw[-1] - lid_yaw[0]), 1),
                   total_turn_imu_deg=round(math.degrees(iy[-1] - iy[0]), 1))
    # forward direction in the LiDAR (levelled, body-yaw) frame
    angs, dists = [], []
    ct = np.array([[c[0], c[1], c[2]] for c in cmds]) if cmds else np.zeros((0, 3))
    wall_t = traj[:, 0]
    for i in range(k, len(traj)):
        j = np.searchsorted(ct[:, 0], wall_t[i]) - 1 if len(ct) else -1
        if j < 0 or ct[j, 1] <= 0 or abs(ct[j, 2]) > 1e-6:
            continue
        d = traj[i, 1:3] - traj[i - k, 1:3]
        if np.linalg.norm(d) < 0.05:
            continue
        heading = traj[i - k, 4]
        ang = math.atan2(d[1], d[0]) - heading
        angs.append(math.remainder(ang, 2 * math.pi))
        dists.append(float(np.linalg.norm(d)))
    if angs:
        a = np.array(angs)
        out.update(forward_windows=len(a),
                   forward_dir_in_lidar_deg=round(math.degrees(math.atan2(np.sin(a).mean(), np.cos(a).mean())), 1),
                   forward_dir_spread_deg=round(math.degrees(np.std(np.unwrap(a))), 1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1])
