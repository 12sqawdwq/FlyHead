#!/usr/bin/env python3
"""Replay a base-continuation session and score drift against the base map.

Per frame after attach: fraction of scan points within 0.15 m of the base map
(areas the old session saw), plus estimated speed while a forward command was
active.  Variants are selected by module constants of slam.py.

  venv/bin/python server/drift_eval.py runs/<id>/raw.xt runs/base.npy
"""
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np

from flyhead.slam import reloc as RL
from flyhead.slam import lidar_slam as S

VARIANTS = {
    'current': {},
    'damp1': dict(VEL_DAMP=1.0),
    'no_imu_prior': dict(IMU_PRIOR=False, VEL_DAMP=1.0),
    'no_seed': dict(SEED_RADIUS=0.0),
    'self_off': dict(SELF_FILTER=False),
    'vox015': dict(VOXEL=0.15),
    'vox020': dict(VOXEL=0.20),
}


def replay(raw, base, consts):
    saved = {k: getattr(S, k) for k in consts}
    for k, v in consts.items():
        setattr(S, k, v)
    try:
        e = S.SlamEngine(Path('/tmp/xt_drift'), base=base)
        imus, frames, cmds, w0 = [], [], [], None
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
                    imus.append(struct.unpack('<d10f', p))
                    if len(imus) >= 25:
                        e.add_imu(imus)
                        imus = []
                elif kind == 3:
                    d = json.loads(p)
                    if d.get('event') == 'status' and d.get('cmd'):
                        cmds.append((wall - w0, d['cmd'][0], d['cmd'][1]))
                elif kind == 1:
                    st, m = struct.unpack('<dI', p[:12])
                    e.add_cloud(st, np.frombuffer(p, '<f4', offset=12, count=m * 5).reshape(m, 5))
                    if not e.attached:
                        time.sleep(0.12)     # real-time pace until relocalised
                    sc = e.take_scan()
                    if sc is not None:
                        W, pts = sc
                        frames.append((wall - w0, W[:3, 3].copy(), pts[::8].copy()))
        e.close()
        return e, frames, cmds
    finally:
        for k, v in saved.items():
            setattr(S, k, v)


def score(base, frames, cmds):
    fits = []
    for t, pos, pts in frames:
        d, _ = base.tree.query(pts.astype(np.float64))
        # only judge points in areas the base map covers (within 0.5 m of something)
        cov = d < 0.5
        if cov.sum() > 50:
            fits.append((t, float((d[cov] < 0.15).mean())))
    fits = np.array(fits)
    # speed while forward-only command active
    ct = np.array(cmds) if cmds else np.zeros((0, 3))
    tt = np.array([f[0] for f in frames])
    P = np.array([f[1] for f in frames])
    speeds = []
    for i in range(1, len(tt)):
        dt = tt[i] - tt[i - 1]
        if dt <= 0 or not len(ct):
            continue
        j = np.searchsorted(ct[:, 0], tt[i]) - 1
        if j >= 0 and tt[i] - ct[j, 0] < 0.6 and ct[j, 1] > 0 and abs(ct[j, 2]) < 1e-6:
            speeds.append((np.linalg.norm(P[i, :2] - P[i - 1, :2]) / dt, ct[j, 1]))
    sp = np.array(speeds) if speeds else np.zeros((0, 2))
    return dict(frames=len(frames), fit_mean=round(float(fits[:, 1].mean()), 3) if len(fits) else None,
                fit_p10=round(float(np.percentile(fits[:, 1], 10)), 3) if len(fits) else None,
                fit_last60s=round(float(fits[fits[:, 0] > fits[-1, 0] - 60, 1].mean()), 3) if len(fits) else None,
                fwd_speed_est=round(float(np.median(sp[:, 0])), 3) if len(sp) else None,
                fwd_cmd=round(float(np.median(sp[:, 1])), 3) if len(sp) else None,
                end_pos=[round(v, 2) for v in P[-1].tolist()] if len(P) else None)


def main():
    raw, base_path = sys.argv[1], sys.argv[2]
    names = sys.argv[3:] or list(VARIANTS)
    base = RL.BaseMap(RL.load_points(base_path))
    for name in names:
        e, frames, cmds = replay(raw, base, VARIANTS[name])
        print(name, json.dumps(score(base, frames, cmds)), 'reloc', json.dumps({k: v for k, v in (e.reloc_info or {}).items() if k != 'T'}), flush=True)


if __name__ == '__main__':
    main()
