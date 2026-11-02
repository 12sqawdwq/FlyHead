#!/usr/bin/env python3
"""Export a saved SLAM map as a navigation package.

Outputs (ROS map_server compatible 2-D grid + 3-D cloud + metadata):
  map.pgm / map.yaml   occupancy grid: 0 occupied, 254 free, 205 unknown
  map_preview.png      same grid, with the recorded trajectory in red
  map.ply              full 3-D point cloud (map frame)
  trajectory.csv       recorded robot body trajectory (map frame)
  MAP_INFO.json        frame definition, parameters, lineage, statistics
  floor.npy            per-cell floor height (map z), float32 [ix, iy]
  obst_hmin.npy        per-cell lowest obstacle point above floor (inf = none), float16
  obst_hmax.npy        per-cell highest obstacle point above floor (-inf = none), float16
                       -> height-aware planning (crouch vs stand) and change detection

The floor height is estimated per TILE (robust to small ramps and residual
vertical drift); a cell is occupied when it has points OCC_BAND above its local
floor, free when it has floor returns and no obstacle, otherwise unknown.

  venv/bin/python tools/export_nav.py runs/<session> maps/<name>
"""
import json
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_closing, binary_opening, median_filter
from scipy.spatial import cKDTree

from flyhead.slam import reloc as RL

RES = 0.05
TILE = 0.5
FLOOR_TOL = 0.06           # |z - local floor| below this counts as floor
OCC_BAND = (0.08, 1.20)    # obstacle heights above local floor (the 2-D map.pgm uses this band)
HEIGHT_LAYER_MAX = 2.48    # height layers keep obstacle points up to this height above floor
BIN_H = 0.15               # obst_bins.npy: bit k = points at OCC_BAND[0] + [k, k+1) * BIN_H above floor
BIN_MIN_PTS = 2            # points needed to set a bin (speckle)
MIN_OCC_PTS = 2            # points per cell to mark occupied (suppress speckle)
FLOOR_MAX_DEV = 0.30       # tile floor must lie within this of the trajectory-based reference
HOLE_FILL = 3              # close free-space holes up to ~this many cells (L1 floor returns are sparse)


def png_gray_rgb(img, path):
    h, w = img.shape[:2]
    rgb = img if img.ndim == 3 else np.repeat(img[:, :, None], 3, axis=2)
    raw = b''.join(b'\x00' + rgb[r].tobytes() for r in range(h))
    chunk = lambda t, x: struct.pack('>I', len(x)) + t + x + struct.pack('>I', zlib.crc32(t + x) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def local_floor(pts, lo, shape_t, traj):
    """Per-tile floor height = 5th percentile of returns in the tile, accepted only
    near a reference derived from the robot trajectory (tiles seen only as walls or
    ceiling, e.g. beyond windows, would otherwise get a floor metres too high)."""
    tij = np.floor((pts[:, :2] - lo) / TILE).astype(int)
    key = tij[:, 0] * shape_t[1] + tij[:, 1]
    order = np.argsort(key, kind='stable')
    k_sorted, z_sorted = key[order], pts[order, 2]
    floor = np.full(shape_t[0] * shape_t[1], np.nan)
    starts = np.r_[0, np.flatnonzero(np.diff(k_sorted)) + 1]
    ends = np.r_[starts[1:], len(k_sorted)]
    for s, e in zip(starts, ends):
        if e - s >= 20:
            floor[k_sorted[s]] = np.percentile(z_sorted[s:e], 5)
    floor = floor.reshape(shape_t)
    # reference: LiDAR height along the trajectory minus the LiDAR height above floor
    centers = lo + (np.stack(np.meshgrid(np.arange(shape_t[0]), np.arange(shape_t[1]), indexing='ij'), -1) + 0.5) * TILE
    tree = cKDTree(traj[:, 1:3])
    _, near = tree.query(centers.reshape(-1, 2))
    tz = traj[near, 3].reshape(shape_t)
    on_path = np.floor((traj[:, 1:3] - lo) / TILE).astype(int)
    diffs = tz[on_path[:, 0], on_path[:, 1]] - floor[on_path[:, 0], on_path[:, 1]]
    lidar_h = float(np.nanmedian(diffs))
    ref = tz - lidar_h
    bad = np.isnan(floor) | (np.abs(floor - ref) > FLOOR_MAX_DEV)
    floor[bad] = np.nan
    local_floor.stats = dict(lidar_height_above_floor_m=round(lidar_h, 3), tiles_rejected=int(bad.sum()))
    # fill tiles without enough returns from neighbours, then smooth outliers
    filled = floor.copy()
    for _ in range(6):
        nanm = np.isnan(filled)
        if not nanm.any():
            break
        pad = np.pad(filled, 1, constant_values=np.nan)
        neigh = np.stack([pad[1 + dy:pad.shape[0] - 1 + dy, 1 + dx:pad.shape[1] - 1 + dx]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
        with np.errstate(all='ignore'):
            est = np.nanmedian(neigh, axis=0)
        filled[nanm] = est[nanm]
    filled = np.where(np.isnan(filled), ref, filled)
    return median_filter(filled, size=3), tij


def main(session, out):
    session, out = Path(session), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    pts = RL.load_points(session / 'map.ply')
    lo = pts[:, :2].min(0) - 0.5
    hi = pts[:, :2].max(0) + 0.5
    shape_t = tuple((np.ceil((hi - lo) / TILE).astype(int) + 1).tolist())
    traj = np.genfromtxt(session / 'trajectory.csv', delimiter=',', skip_header=1).reshape(-1, 5)
    floor_t, tij = local_floor(pts, lo, shape_t, traj)
    h_above = pts[:, 2] - floor_t[tij[:, 0], tij[:, 1]]

    W, H = (np.ceil((hi - lo) / RES).astype(int) + 1)
    ij = np.floor((pts[:, :2] - lo) / RES).astype(int)
    # ---- height layers (for variable robot height and height-aware change detection) ----
    ftile_ij = np.floor((lo + (np.stack(np.meshgrid(np.arange(W), np.arange(H), indexing='ij'), -1) + 0.5) * RES
                         - lo) / TILE).astype(int)
    floor_cells = floor_t[np.clip(ftile_ij[..., 0], 0, shape_t[0] - 1), np.clip(ftile_ij[..., 1], 0, shape_t[1] - 1)]
    tall = (h_above > OCC_BAND[0]) & (h_above < HEIGHT_LAYER_MAX)
    hmin = np.full((W, H), np.inf, np.float32)
    hmax = np.full((W, H), -np.inf, np.float32)
    ij_t = np.floor((pts[tall, :2] - lo) / RES).astype(int)
    np.minimum.at(hmin, (ij_t[:, 0], ij_t[:, 1]), h_above[tall].astype(np.float32))
    np.maximum.at(hmax, (ij_t[:, 0], ij_t[:, 1]), h_above[tall].astype(np.float32))
    np.save(out / 'floor.npy', floor_cells.astype(np.float32))
    np.save(out / 'obst_hmin.npy', hmin.astype(np.float16))
    np.save(out / 'obst_hmax.npy', hmax.astype(np.float16))
    # 16 height bins of BIN_H from OCC_BAND[0]: which heights in each cell actually had points
    b = np.clip(((h_above[tall] - OCC_BAND[0]) / BIN_H).astype(int), 0, 15)
    cnt = np.zeros((W, H, 16), np.uint16)
    np.add.at(cnt, (ij_t[:, 0], ij_t[:, 1], b), 1)
    bits = ((cnt >= BIN_MIN_PTS).astype(np.uint32) << np.arange(16, dtype=np.uint32)).sum(axis=2).astype(np.uint16)
    np.save(out / 'obst_bins.npy', bits)

    occ_cnt = np.zeros((W, H), np.int32)
    flo_cnt = np.zeros((W, H), np.int32)
    ob = (h_above > OCC_BAND[0]) & (h_above < OCC_BAND[1])
    fl = np.abs(h_above) < FLOOR_TOL
    np.add.at(occ_cnt, (ij[ob, 0], ij[ob, 1]), 1)
    np.add.at(flo_cnt, (ij[fl, 0], ij[fl, 1]), 1)
    occ = binary_opening(occ_cnt >= MIN_OCC_PTS, np.ones((2, 2))) | (occ_cnt >= 6)
    free = binary_closing(flo_cnt > 0, np.ones((HOLE_FILL, HOLE_FILL))) & ~occ

    grid = np.full((W, H), 205, np.uint8)
    grid[free] = 254
    grid[occ] = 0
    img = np.flipud(grid.T)                     # row 0 = max y (map_server convention)
    (out / 'map.pgm').write_bytes(b'P5\n%d %d\n255\n' % (W, H) + img.tobytes())
    (out / 'map.yaml').write_text(
        'image: map.pgm\nmode: trinary\nresolution: %.3f\norigin: [%.4f, %.4f, 0.0]\n'
        'negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n' % (RES, lo[0], lo[1]))

    shutil.copy(session / 'map.ply', out / 'map.ply')
    shutil.copy(session / 'trajectory.csv', out / 'trajectory.csv')
    prev = np.repeat(img[:, :, None], 3, axis=2).copy()
    tj = np.floor((traj[:, 1:3] - lo) / RES).astype(int)
    ok = (tj[:, 0] >= 0) & (tj[:, 0] < W) & (tj[:, 1] >= 0) & (tj[:, 1] < H)
    prev[H - 1 - tj[ok, 1], tj[ok, 0]] = (220, 40, 40)
    png_gray_rgb(prev, out / 'map_preview.png')

    base = json.loads((session / 'BASE.json').read_text()) if (session / 'BASE.json').exists() else None
    summary = json.loads((session / 'summary.json').read_text())
    info = dict(
        created=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        source_session=str(session), base_of_source=base,
        lineage=['live_20260925T204520 (first 1098 s, before the LiDAR/link gap)',
                 'live_20260925T213534 (relocalised onto it; rebuilt offline from raw.xt)',
                 'live_20260925T215907 (relocalised onto the merged map; saved ' +
                 time.strftime('%H:%M:%S', time.localtime((session / 'map.ply').stat().st_mtime)) + ')'],
        frame=dict(
            name='xt_map',
            definition='gravity-levelled frame of the L1 LiDAR at the start of live_20260925T204520; '
                       'z up, z=0 at that LiDAR height (not the floor)',
            robot_body_yaw_from_lidar_deg=180.0,
            note='trajectory.csv yaw is the robot body heading (x forward)'),
        grid=dict(resolution=RES, width=int(W), height=int(H), origin=[float(lo[0]), float(lo[1]), 0.0],
                  floor_tile_m=TILE, floor_tolerance_m=FLOOR_TOL, obstacle_band_above_floor_m=list(OCC_BAND),
                  occupied_cells=int(occ.sum()), free_cells=int(free.sum()),
                  hole_fill_cells=HOLE_FILL, floor_max_dev_from_reference_m=FLOOR_MAX_DEV,
                  **local_floor.stats,
                  floor_height_range_m=[round(float(np.nanmin(floor_t)), 3), round(float(np.nanmax(floor_t)), 3)]),
        cloud=dict(points=int(len(pts)), voxel_m=0.05),
        height_layers=dict(files=['floor.npy', 'obst_hmin.npy', 'obst_hmax.npy', 'obst_bins.npy'],
                           bins=dict(count=16, base_m=OCC_BAND[0], height_m=BIN_H, min_points=BIN_MIN_PTS),
                           index='[ix, iy] same as map.pgm grid',
                           max_height_m=HEIGHT_LAYER_MAX,
                           note='a cell blocks a robot of height H if obst_hmin <= H (+margin)'),
        slam=dict(method='KISS-ICP LiDAR odometry + IMU rotational deskew/prior, map-anchored continuation',
                  loop_closure=False, last_session_summary={k: summary.get(k) for k in
                                                            ('frames', 'distance_m', 'map_points', 'reloc')}),
        caveats=['No global pose-graph optimisation / loop closure; long loops may carry residual drift.',
                 'Obstacles lower than 8 cm above local floor and drops/stairs are NOT marked occupied.',
                 'Glass, mirrors and thin legs may be missing; moving people seen while mapping may be marked.',
                 'Unknown (205) cells were never observed as floor; treat as not traversable.'])
    (out / 'MAP_INFO.json').write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(json.dumps(dict(out=str(out), grid=info['grid'], points=len(pts)), ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: export_nav.py <session dir> <output package dir>')
    main(sys.argv[1], sys.argv[2])
