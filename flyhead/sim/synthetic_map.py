"""Synthetic navigation map package for simulation without a recorded map.

Writes map.pgm + map.yaml in the format flyhead.slam.navmap.NavMap reads (0 occupied / 254 free,
0.05 m cells) and the height layers of tools/export_nav.py (floor.npy, obst_hmin/hmax.npy,
obst_bins.npy; flat floor at z = 0, obstacles WALL_TOP high). The navigator needs the floor layer
to know the LiDAR height; without it the brain link ignores every scan. A walled arena with a few pillars, laid out so the scenarios in loom_sim.py and the
start pose of reflex_sim.py have the clearances they were designed for (open area around (7, -1.1),
a lane toward a far wall from (5.6, 6.45)). It reproduces the pipeline, not the recorded numbers:
the published experiment results were obtained on a recorded map that is not part of this repo.

python -m flyhead.sim.synthetic_map OUT_DIR
"""
import sys
from pathlib import Path

import numpy as np

from flyhead.slam.navmap import write_pgm

RES = 0.05
ORIGIN = (-1.0, -8.0)
SIZE_M = (16.0, 20.0)
ARENA = (1.0, 13.0, -5.5, 9.5)            # x0, x1, y0, y1 of the inner wall faces
WALL_M = 0.20
PILLARS = [(10.0, 5.0, 0.30), (3.0, 7.5, 0.40), (11.5, -4.0, 0.30)]   # (x, y, radius)
BOXES = [(2.6, 2.4, 3.6, 3.4)]             # x0, y0, x1, y1
WALL_TOP = 1.5                             # obstacle height above the floor (m)
BINS_BASE, BINS_H = 0.08, 0.15             # as navmap / export_nav (obst_bins.npy)


def build():
    nx, ny = int(round(SIZE_M[0] / RES)), int(round(SIZE_M[1] / RES))
    x = ORIGIN[0] + (np.arange(nx) + 0.5) * RES
    y = ORIGIN[1] + (np.arange(ny) + 0.5) * RES
    X, Y = np.meshgrid(x, y, indexing='ij')
    x0, x1, y0, y1 = ARENA
    inside = (X > x0) & (X < x1) & (Y > y0) & (Y < y1)
    wall = (X > x0 - WALL_M) & (X < x1 + WALL_M) & (Y > y0 - WALL_M) & (Y < y1 + WALL_M) & ~inside
    for px, py, r in PILLARS:
        wall |= (X - px) ** 2 + (Y - py) ** 2 <= r * r
    for bx0, by0, bx1, by1 in BOXES:
        wall |= (X >= bx0) & (X <= bx1) & (Y >= by0) & (Y <= by1)
    grid = np.full((nx, ny), 205, np.uint8)        # unknown outside the arena
    grid[inside] = 254
    grid[wall] = 0
    return grid


def write(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    grid = build()
    write_pgm(grid, out / 'map.pgm')
    occupied = grid == 0
    np.save(out / 'floor.npy', np.zeros(grid.shape, np.float32))
    np.save(out / 'obst_hmin.npy', np.where(occupied, BINS_BASE, np.inf).astype(np.float16))
    np.save(out / 'obst_hmax.npy', np.where(occupied, WALL_TOP, -np.inf).astype(np.float16))
    n_bins = int(np.ceil((WALL_TOP - BINS_BASE) / BINS_H))
    np.save(out / 'obst_bins.npy', np.where(occupied, (1 << n_bins) - 1, 0).astype(np.uint16))
    (out / 'map.yaml').write_text('image: map.pgm\nmode: trinary\nresolution: %.3f\norigin: [%.4f, %.4f, 0.0]\n'
                                  'negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n' % (RES, ORIGIN[0], ORIGIN[1]))
    return out


if __name__ == '__main__':
    print(write(sys.argv[1] if len(sys.argv) > 1 else 'maps/synthetic_arena'))
