"""Navigation map layers (xt_map frame, grid index [ix, iy], 0.05 m cells).

  static   nav package map.pgm: 0 occupied / 254 free / 205 unknown, plus height layers
  live     per-cell hit/pass evidence from the current LiDAR scans (2-D ray casting)
  changes  confirmed differences vs static: 'added' (new obstacle on free floor)
           and 'removed' (static obstacle repeatedly seen through)
"""
import json
import math
import threading
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion, distance_transform_edt, find_objects, label

LIVE_RANGE = 8.0             # live evidence is gathered within this range
BAND = (0.08, 1.20)          # obstacle band above floor
# The session frame drifts vertically against the base map (live_20261008T101201: floor
# 0.04-0.09 m higher, ~1.6 deg tilt after 57 m), which lifted floor returns into the obstacle
# band and produced phantom obstacles 1-2 m ahead.  Each scan re-fits that offset as a plane
# through its own near-floor returns and removes it before the height tests.
FLOOR_FIT_WINDOW = 0.15      # returns this close to the map floor are floor candidates
FLOOR_FIT_INLIER = 0.03      # residual kept by the trimmed refit
FLOOR_FIT_MIN = 200          # fewer candidates: no correction
FLOOR_FIT_MAX_OFFSET = 0.15
FLOOR_FIT_MAX_SLOPE = 0.05   # ~3 deg
HIT_DECAY = 0.92             # per frame evidence decay
ADD_HITS = 4.0               # decayed hits to call a free cell occupied now
REMOVE_PASSES = 8.0          # decayed passes (with no hits) to call a static obstacle gone
CONFIRM_S = 1.5              # a change must persist this long before it is committed
MIN_CLUSTER = 12             # cells (0.05 m) per change cluster (>= 0.03 m^2)
CROUCH_LIDAR_H = 0.20
ROBOT_HEIGHT = {'crouch': 0.32, 'stand': 0.45}   # fallbacks when the LiDAR height is unknown
HEIGHT_MARGIN = 0.10
BINS_BASE, BINS_H = 0.08, 0.15    # must match export_nav.py (obst_bins.npy)


def load_pgm(path):
    data = Path(path).read_bytes()
    parts = data.split(b'\n', 3)
    w, h = map(int, parts[1].split())
    img = np.frombuffer(parts[3], np.uint8, count=w * h).reshape(h, w)
    return np.flipud(img).T.copy()          # -> grid[ix, iy], iy up


def write_pgm(grid, path):
    img = np.flipud(grid.T)
    tmp = Path(str(path) + '.tmp')
    tmp.write_bytes(b'P5\n%d %d\n255\n' % (grid.shape[0], grid.shape[1]) + img.tobytes())
    tmp.replace(path)


class NavMap:
    def __init__(self, pkg):
        self.pkg = Path(pkg)
        meta = {}
        for line in (self.pkg / 'map.yaml').read_text().splitlines():
            k, _, v = line.partition(':')
            meta[k.strip()] = v.strip()
        self.res = float(meta['resolution'])
        self.origin = np.array([float(x) for x in meta['origin'].strip('[]').split(',')[:2]])
        self.static = load_pgm(self.pkg / meta['image'])
        self.shape = self.static.shape
        hl = self.pkg / 'obst_hmin.npy'
        if hl.exists():
            self.floor = np.load(self.pkg / 'floor.npy').astype(np.float32)
            self.hmin = np.load(hl).astype(np.float32)
            self.hmax = np.load(self.pkg / 'obst_hmax.npy').astype(np.float32)
            assert self.hmin.shape == self.shape, 'height layers do not match map.pgm'
            bp = self.pkg / 'obst_bins.npy'
            self.bins = np.load(bp).astype(np.uint32) if bp.exists() else None
        else:
            self.floor = self.hmin = self.hmax = self.bins = None
        self._block_cache = {}

    def blocked_for(self, height):
        """Static cells that block a robot of this height (overhangs above it do not)."""
        key = round(height, 2)
        if key not in self._block_cache:
            if self.bins is not None:
                n = int(np.clip(math.ceil((height + HEIGHT_MARGIN - BINS_BASE) / BINS_H), 1, 16))
                b = (self.bins & np.uint32((1 << n) - 1)) != 0      # any occupied bin below the robot top
            elif self.hmin is not None:
                b = self.hmin <= height + HEIGHT_MARGIN
            else:
                b = self.static == 0
            if self.hmin is not None:
                # drop isolated single-cell returns (speckle)
                nb = sum(np.roll(np.roll(b, dx, 0), dy, 1) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                b &= nb >= 2
            self._block_cache[key] = b
        return self._block_cache[key]

    def clearance_for(self, height):
        """Distance (m) from every cell to the nearest static cell that blocks this height."""
        key = ('clearance', round(height, 2))
        if key not in self._block_cache:
            self._block_cache[key] = (distance_transform_edt(~self.blocked_for(height)) * self.res).astype(np.float32)
        return self._block_cache[key]

    def floor_at(self, xy):
        ij = self.to_ij(xy)
        ok = self.inside(ij)
        f = np.full(len(ij), np.nan, np.float32)
        if self.floor is not None:
            f[ok] = self.floor[ij[ok, 0], ij[ok, 1]]
        return f

    def to_ij(self, xy):
        return np.floor((np.asarray(xy) - self.origin) / self.res).astype(int)

    def to_xy(self, ij):
        return self.origin + (np.asarray(ij) + 0.5) * self.res

    def inside(self, ij):
        return (ij[..., 0] >= 0) & (ij[..., 0] < self.shape[0]) & (ij[..., 1] >= 0) & (ij[..., 1] < self.shape[1])


class LiveLayer:
    """Decayed hit/pass evidence per 0.05 m cell from 2-D ray casting."""

    def __init__(self, nm: NavMap):
        self.nm = nm
        self.hits = np.zeros(nm.shape, np.float32)
        self.passes = np.zeros(nm.shape, np.float32)
        self.last_update = 0.0
        self.hits.setflags(write=False)
        self.passes.setflags(write=False)
        self.published = (self.hits, self.passes, 0.0)
        self.lidar_h_guess = CROUCH_LIDAR_H
        self.nearest = None
        self.floor_offset = None

    def fit_floor_offset(self, rel_xy, dz):
        """Plane (a, bx, by) of the scan floor above the map floor, or None."""
        m = np.abs(dz) < FLOOR_FIT_WINDOW
        for _ in range(2):
            if m.sum() < FLOOR_FIT_MIN:
                return None
            A = np.c_[np.ones(m.sum()), rel_xy[m]]
            coef = np.linalg.lstsq(A, dz[m], rcond=None)[0]
            m = m & (np.abs(np.c_[np.ones(len(dz)), rel_xy] @ coef - dz) < FLOOR_FIT_INLIER)
        if (m.sum() < FLOOR_FIT_MIN or abs(coef[0]) > FLOOR_FIT_MAX_OFFSET
                or np.hypot(coef[1], coef[2]) > FLOOR_FIT_MAX_SLOPE):
            return None
        return coef

    def update(self, sensor_xyz, world, robot_height=ROBOT_HEIGHT['crouch'], observed_at=None):
        nm = self.nm
        d = np.linalg.norm(world[:, :2] - sensor_xyz[:2], axis=1)
        sel = (d > 0.3) & (d < LIVE_RANGE)
        world = world[sel]
        floor = nm.floor_at(world[:, :2])
        known = np.isfinite(floor)
        rel_xy = world[:, :2] - sensor_xyz[:2]
        coef = self.fit_floor_offset(rel_xy[known], world[known, 2] - floor[known]) if known.any() else None
        self.floor_offset = None if coef is None else float(coef[0])
        if coef is not None:
            world = world.copy()
            world[:, 2] -= np.c_[np.ones(len(world)), rel_xy] @ coef
            sensor_xyz = np.array(sensor_xyz, dtype=float)
            sensor_xyz[2] -= coef[0]
        fallback = sensor_xyz[2] - self.lidar_h_guess
        floor = np.where(known, floor, fallback)
        h = world[:, 2] - floor
        # live obstacles: anything the robot at its current height would hit
        obs = world[(h > BAND[0]) & (h < robot_height + HEIGHT_MARGIN)]
        self.nearest = float(np.min(np.linalg.norm(obs[:, :2] - sensor_xyz[:2], axis=1))) if len(obs) else None
        # rays to returns within the static obstacle band (see below)
        ray_tgt = world[(h > BAND[0]) & (h < BAND[1])]
        # Only rays to obstacle-band returns count as passing through a cell: they stay within
        # the obstacle band all the way (LiDAR ~0.2 m above floor).  Rays to floor returns would
        # pass under tables and falsely 'remove' them.
        tgt = ray_tgt
        hits = self.hits * HIT_DECAY
        if len(obs):
            ij = nm.to_ij(obs[:, :2])
            ij = ij[nm.inside(ij)]
            if len(ij):
                hits.ravel()[np.unique(ij[:, 0] * nm.shape[1] + ij[:, 1])] += 1.0
        hits.setflags(write=False)
        self.hits = hits
        self.last_update = time.time()
        stamp = self.last_update if observed_at is None else observed_at
        self.published = (hits, self.passes, stamp)
        return sensor_xyz, tgt

    def update_passes(self, sensor_xyz, tgt):
        """Slow, single-writer free-space evidence; never delays hit publication."""
        nm = self.nm
        passes = self.passes * HIT_DECAY
        visited = np.zeros(passes.size, dtype=bool)
        # Bound scratch arrays without discarding rays or changing height tests.
        for offset in range(0, len(tgt), 256):
            targets = tgt[offset:offset + 256]
            if len(targets):
                o = sensor_xyz
                v = targets - o
                L = np.linalg.norm(v[:, :2], axis=1)
                n = np.maximum((L / (nm.res * 0.7)).astype(int) - 4, 0)   # stop ~0.14 m short of the endpoint
                k = np.repeat(np.arange(len(targets)), n)
                step = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
                frac = ((step + 0.5) * nm.res * 0.7 / L[k])
                pts = o + v[k] * frac[:, None]                   # 3-D samples along each ray
                ij = nm.to_ij(pts[:, :2])
                ok = nm.inside(ij)
                ij, pts = ij[ok], pts[ok]
                if len(ij) and nm.hmin is not None:
                    # A ray only disproves a static obstacle where it passes at the height
                    # the obstacle had points (rays under a table top prove nothing about it).
                    hs = pts[:, 2] - nm.floor[ij[:, 0], ij[:, 1]]
                    static_cell = np.isfinite(nm.hmin[ij[:, 0], ij[:, 1]])
                    if nm.bins is not None:
                        # the ray must cross a height bin that actually had points in the map
                        k = np.clip(((hs - BINS_BASE) / BINS_H).astype(int), 0, 15)
                        had = (nm.bins[ij[:, 0], ij[:, 1]] >> k.astype(np.uint32)) & 1
                        valid = ~static_cell | ((had == 1) & (hs > BINS_BASE))
                    else:
                        lo_h, hi_h = nm.hmin[ij[:, 0], ij[:, 1]], nm.hmax[ij[:, 0], ij[:, 1]]
                        valid = ~static_cell | ((hs >= lo_h - 0.05) & (hs <= hi_h + 0.05))
                    ij = ij[valid]
                if len(ij):
                    visited[ij[:, 0] * nm.shape[1] + ij[:, 1]] = True
        passes.ravel()[visited] += 1.0
        passes.setflags(write=False)
        self.passes = passes
        return passes

    def snapshot(self):
        """Reference handoff only; callers must not mutate published arrays."""
        return self.published[:2]


class ChangeTracker:
    """Confirm persistent differences vs the static map and commit them."""

    def __init__(self, nm: NavMap, out_dir: Path, on_commit=None):
        self.nm = nm
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.added = np.zeros(nm.shape, bool)      # committed
        self.removed = np.zeros(nm.shape, bool)
        self.cand_since = {}                        # (kind, ix, iy) cluster key -> first seen
        self.events = []
        self.version = 0
        self.on_commit = on_commit
        self.auto_submit = True
        self.pending = []
        self.lock = threading.Lock()
        occ = nm.static == 0
        self.static_core = binary_erosion(occ, np.ones((3, 3)))            # interior of static obstacles
        self.near_static = binary_dilation(occ, np.ones((5, 5)))           # within 0.1 m of static obstacles

    def clusters(self, mask):
        """Connected cells >= MIN_CLUSTER.  One labelling pass + bounding boxes: scanning
        the whole grid once per cluster froze the Pi (hundreds of noise clusters)."""
        lab, n = label(mask, np.ones((3, 3)))
        if n == 0:
            return []
        sizes = np.bincount(lab.ravel())
        out = []
        for i, sl in enumerate(find_objects(lab), 1):
            if sl is None or sizes[i] < MIN_CLUSTER:
                continue
            ij = np.argwhere(lab[sl] == i) + np.array([sl[0].start, sl[1].start])
            out.append(ij)
        return out

    def step(self, hits, passes, robot_xy=None):
        if robot_xy is None:
            return []
        now = time.time()
        # only the live-evidence window around the robot (the rest cannot change)
        c0 = self.nm.to_ij(robot_xy)
        R = int(LIVE_RANGE / self.nm.res) + 2
        x0, x1 = max(c0[0] - R, 0), min(c0[0] + R + 1, self.nm.shape[0])
        y0, y1 = max(c0[1] - R, 0), min(c0[1] + R + 1, self.nm.shape[1])
        win = (slice(x0, x1), slice(y0, y1))
        hits, passes = hits[win].copy(), passes[win].copy()
        # never judge changes on the robot's own footprint (old body returns in the map)
        r = int(math.ceil(0.7 / self.nm.res))
        cx, cy = c0[0] - x0, c0[1] - y0
        hits[max(cx - r, 0):cx + r + 1, max(cy - r, 0):cy + r + 1] = 0
        passes[max(cx - r, 0):cx + r + 1, max(cy - r, 0):cy + r + 1] = 0
        added_now = (self.nm.static[win] == 254) & ~self.near_static[win] & (hits >= ADD_HITS) & ~self.added[win]
        removed_now = self.static_core[win] & (passes >= REMOVE_PASSES) & (hits < 0.5) & ~self.removed[win]
        # an obstacle committed as added that is seen through again is cleared
        cleared = self.added[win] & (passes >= REMOVE_PASSES) & (hits < 0.5)
        off = np.array([x0, y0])
        new_events = []
        seen = set()
        for kind, mask in (('added', added_now), ('removed', removed_now)):
            for ij in self.clusters(mask):
                ij = ij + off
                c = ij.mean(0)
                key = (kind, int(c[0] // 6), int(c[1] // 6))   # ~0.3 m buckets
                seen.add(key)
                first = self.cand_since.setdefault(key, now)
                if now - first >= CONFIRM_S:
                    xy = self.nm.to_xy(c)
                    lo, hi = self.nm.to_xy(ij.min(0)), self.nm.to_xy(ij.max(0))
                    ev = dict(t=now, kind=kind, x=round(float(xy[0]), 2), y=round(float(xy[1]), 2),
                              bbox=[round(float(v), 2) for v in (*lo, *hi)],
                              area_m2=round(len(ij) * self.nm.res ** 2, 3), cells=int(len(ij)))
                    with self.lock:
                        (self.added if kind == 'added' else self.removed)[ij[:, 0], ij[:, 1]] = True
                    new_events.append(ev)
                    self.cand_since.pop(key, None)
        for key in list(self.cand_since):
            if key not in seen:
                self.cand_since.pop(key)
        if cleared.any():
            with self.lock:
                self.added[win] &= ~cleared
            new_events.append(dict(t=now, kind='cleared', cells=int(cleared.sum())))
        if new_events:
            with self.lock:
                self.events.extend(new_events)
                self.pending.extend(new_events)
            if self.auto_submit:
                self.submit()
        return new_events

    def merged_grid(self):
        g = self.nm.static.copy()
        with self.lock:
            g[self.removed] = 254
            g[self.added] = 0
        return g

    def submit(self):
        """Commit to the shared ('cloud') map on this server: versioned grid + change log."""
        with self.lock:
            pending, self.pending = self.pending, []
            self.version += 1
            version = self.version
        g = self.merged_grid()
        write_pgm(g, self.out / 'map_live.pgm')
        (self.out / 'map_live.yaml').write_text((self.nm.pkg / 'map.yaml').read_text().replace('map.pgm', 'map_live.pgm'))
        with open(self.out / 'changes.jsonl', 'a') as f:
            for ev in pending:
                f.write(json.dumps(dict(ev, version=version), ensure_ascii=False) + '\n')
        (self.out / 'VERSION.json').write_text(json.dumps(dict(
            version=version, updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'), base_package=str(self.nm.pkg),
            added_cells=int(self.added.sum()), removed_cells=int(self.removed.sum()),
            events_total=len(self.events)), ensure_ascii=False))
        if self.on_commit:
            self.on_commit(version, pending)
        return version
