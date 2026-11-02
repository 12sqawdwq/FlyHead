"""Global relocalization of the current session against the base map.

Robot-vacuum style: both clouds are gravity-levelled, so the search is over
x, y, yaw.  A 2-D wall-band likelihood field of the old map is correlated
(FFT) with the current local submap at every yaw step, the best peaks are
refined with 3-D ICP, and the result is accepted only if the best candidate
clearly beats the next distinct one.  If ambiguous, drive a little further and
re-run: the current submap grows and the ambiguity usually collapses.
"""
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter
from scipy.signal import fftconvolve
from scipy.spatial import cKDTree

RES = 0.10                 # 2-D search grid
BAND = (0.10, 1.80)        # z band (lidar-relative, levelled) = walls/furniture, no floor/ceiling
YAW_STEP = 3.0             # degrees
TOP_CANDIDATES = 5         # candidates refined with ICP
ICP_SRC_VOXEL = 0.25
ICP_ITERS = 20
ICP_MAX_SRC = 4000


def band(p):
    return p[(p[:, 2] > BAND[0]) & (p[:, 2] < BAND[1])]


def rot2(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s], [s, c]])


def rasterize(xy, res):
    lo = np.floor(xy.min(axis=0) / res).astype(int)
    ij = np.floor(xy / res).astype(int) - lo
    g = np.zeros(ij.max(axis=0) + 1, np.float32)
    g[ij[:, 0], ij[:, 1]] = 1.0
    return g, lo


def likelihood_field(map_pts):
    field, m0 = rasterize(band(map_pts)[:, :2], RES)
    field = gaussian_filter(field, 1.0)
    return field / field.max(), m0


def search(field, m0, scan_pts, top=None):
    top = top or TOP_CANDIDATES
    sb = band(scan_pts)[:, :2]
    if len(sb) < 50:
        return []
    cands = []
    for deg in np.arange(0, 360, YAW_STEP):
        yaw = math.radians(deg)
        q = sb @ rot2(yaw).T
        k, o = rasterize(q, RES)
        if k.shape[0] > field.shape[0] or k.shape[1] > field.shape[1]:
            continue
        c = fftconvolve(field, k[::-1, ::-1], mode='valid') / k.sum()
        peaks = (c == maximum_filter(c, size=9)) & (c > 0.2)
        idx = np.argwhere(peaks)
        vals = c[peaks]
        for (i, j), v in sorted(zip(idx.tolist(), vals.tolist()), key=lambda z: -z[1])[:3]:
            t = (m0 + np.array([i, j]) - o) * RES
            cands.append((float(v), float(t[0]), float(t[1]), yaw))
    cands.sort(key=lambda z: -z[0])
    keep = []
    for c in cands:        # non-maximum suppression in pose space
        if all(math.hypot(c[1] - k[1], c[2] - k[2]) > 1.0 or
               abs(math.remainder(c[3] - k[3], 2 * math.pi)) > math.radians(20) for k in keep):
            keep.append(c)
        if len(keep) >= top:
            break
    return keep


def icp(tree, map_pts, src, T, iters=40):
    for it in range(iters):
        max_d = max(0.25, 1.0 * (1 - it / 15))
        q = src @ T[:3, :3].T + T[:3, 3]
        d, i = tree.query(q, distance_upper_bound=max_d)
        ok = np.isfinite(d)
        if ok.sum() < 50:
            break
        a, b = q[ok], map_pts[i[ok]]
        ca, cb = a.mean(0), b.mean(0)
        H = (a - ca).T @ (b - cb)
        U, _, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1] *= -1
            R = Vt.T @ U.T
        # keep the solution levelled: only yaw is free in rotation
        yaw = math.atan2(R[1, 0], R[0, 0])
        R = np.eye(3)
        R[:2, :2] = rot2(yaw)
        dT = np.eye(4)
        dT[:3, :3] = R
        dT[:3, 3] = cb - R @ ca
        T = dT @ T
        if np.linalg.norm(dT[:3, 3]) < 1e-3 and abs(yaw) < 1e-4:
            break
    q = src @ T[:3, :3].T + T[:3, 3]
    d, _ = tree.query(q)
    fit = float((d < 0.15).mean())
    rmse = float(np.sqrt(np.mean(np.minimum(d, 0.15) ** 2)))
    return T, fit, rmse


def voxel(p, s):
    _, i = np.unique(np.floor(p / s).astype(np.int64), axis=0, return_index=True)
    return p[np.sort(i)]


def distinct(a, b):
    return (math.hypot(a['t'][0] - b['t'][0], a['t'][1] - b['t'][1]) > 1.0 or
            abs(math.remainder(math.radians(a['yaw_deg'] - b['yaw_deg']), 2 * math.pi)) > math.radians(20))


class BaseMap:
    """A previous map prepared once for repeated global localisation."""
    MIN_FIT = 0.8      # correct matches scored 0.93-0.995; 0.5 accepted a wrong 0.64 match
    MIN_RATIO = 1.3
    # An operator pose hint replaces only the ambiguity test: a candidate that puts the
    # robot within HINT_RADIUS_M / HINT_YAW_DEG of the hint and still reaches MIN_FIT is
    # accepted although a similar place elsewhere scores close to it.
    HINT_RADIUS_M = 1.0
    HINT_YAW_DEG = 30.0

    def __init__(self, pts):
        self.pts = np.asarray(pts, np.float64)
        self.field, self.m0 = likelihood_field(self.pts)
        self.mv = voxel(self.pts, 0.08)
        self.tree = cKDTree(self.mv)
        self.floor_z = float(np.percentile(self.pts[:, 2], 2))

    def localize(self, scan, hint=None, body=None):
        """scan: levelled points in the session frame. Returns T (session->base) or None.

        hint: optional operator pose (x, y, yaw or None) of the robot body on the base map;
        body: the body pose (x, y, yaw) in the session frame that the hint refers to.

        The wall band is cut relative to the FLOOR: the scan is shifted so its floor
        matches the base floor first (the LiDAR is ~0.2 m up crouched, higher standing)."""
        dz = self.floor_z - float(np.percentile(scan[:, 2], 2))
        scan = scan + np.array([0.0, 0.0, dz])
        cands = search(self.field, self.m0, scan)
        if not cands:
            return dict(confident=False, reason='too few wall points', candidates=[])
        src = voxel(scan, ICP_SRC_VOXEL)
        if len(src) > ICP_MAX_SRC:
            src = src[np.random.default_rng(0).choice(len(src), ICP_MAX_SRC, replace=False)]
        refined = []
        for score, tx, ty, yaw in cands:
            T = np.eye(4)
            T[:2, :2] = rot2(yaw)
            T[:2, 3] = (tx, ty)
            T, fit, rmse = icp(self.tree, self.mv, src, T, iters=ICP_ITERS)
            T = T.copy()
            T[2, 3] += dz                       # express for the unshifted scan
            refined.append(dict(corr=round(score, 3), fitness=round(fit, 3), rmse=round(rmse, 3), T=T,
                                yaw_deg=round(math.degrees(math.atan2(T[1, 0], T[0, 0])), 1),
                                t=[round(T[0, 3], 3), round(T[1, 3], 3), round(T[2, 3], 3)]))
        refined.sort(key=lambda r: -r['fitness'])
        if body is not None:
            for r in refined:
                T = r['T']
                xy = T[:2, :2] @ np.asarray(body[:2], float) + T[:2, 3]
                yaw = math.remainder(body[2] + math.atan2(T[1, 0], T[0, 0]), 2 * math.pi)
                r['robot'] = [round(float(xy[0]), 2), round(float(xy[1]), 2), round(yaw, 3)]
        best = refined[0]
        second = next((r for r in refined[1:] if distinct(r, best)), None)
        ratio = best['fitness'] / second['fitness'] if second and second['fitness'] > 0 else float('inf')
        confident = best['fitness'] >= self.MIN_FIT and ratio >= self.MIN_RATIO
        hinted = False
        if not confident and hint is not None and body is not None:
            for r in refined:
                rx, ry, ryaw = r['robot']
                near = math.hypot(rx - hint[0], ry - hint[1]) <= self.HINT_RADIUS_M
                if hint[2] is not None:
                    near = near and abs(math.degrees(math.remainder(ryaw - hint[2], 2 * math.pi))) <= self.HINT_YAW_DEG
                if near and r['fitness'] >= self.MIN_FIT:
                    best, confident, hinted = r, True, True
                    break
        keys = ('fitness', 'rmse', 'corr', 't', 'yaw_deg', 'robot')
        return dict(confident=confident, hinted=hinted, best=best, second=second, ratio=ratio,
                    candidates=[{k: c[k] for k in keys if k in c} for c in refined[:6]])


def load_points(path):
    path = str(path)
    if path.endswith('.npy'):
        return np.load(path).astype(np.float64)
    data = Path(path).read_bytes()
    i = data.index(b'end_header\n') + len(b'end_header\n')
    return np.frombuffer(data[i:], '<f4').reshape(-1, 3).astype(np.float64)
