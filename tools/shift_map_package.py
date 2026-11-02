"""Copy a saved SLAM map package into a frame where a chosen LiDAR start pose is the origin.

The synthetic console recordings (tools/make_synthetic_raw.py) are generated relative to the LiDAR,
so the base map must sit in the same frame: the LiDAR start pose at (0, 0) and the floor at
-LIDAR_H. This copies map.pgm, the height layers and map.ply of SRC into DST, shifting them by the
start pose. The source package is never modified.

  python tools/shift_map_package.py SRC DST --start X Y [--lidar-h 0.45]

Writes DST/SHIFT.json with the shift applied. Do not publish DST: it is a floor plan of a real site.
"""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from flyhead.slam.navmap import NavMap

LAYERS = ('obst_hmin.npy', 'obst_hmax.npy', 'obst_bins.npy')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--start', type=float, nargs=2, required=True, metavar=('X', 'Y'))
    ap.add_argument('--lidar-h', type=float, default=0.45)
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)
    dst.mkdir(parents=True, exist_ok=False)
    nm = NavMap(src)
    sx, sy = a.start
    floor0 = float(nm.floor_at(np.array([[sx, sy]]))[0])
    if not np.isfinite(floor0):
        raise SystemExit('start pose has no floor in the map')
    dz = floor0 + a.lidar_h                       # LiDAR height in the map frame at the start pose

    shutil.copy(src / 'map.pgm', dst / 'map.pgm')
    for name in LAYERS:
        if (src / name).exists():
            shutil.copy(src / name, dst / name)
    meta = (src / 'map.yaml').read_text().splitlines()
    out = []
    for line in meta:
        if line.startswith('origin:'):
            ox, oy = nm.origin[0] - sx, nm.origin[1] - sy
            line = 'origin: [%.4f, %.4f, 0.0]' % (ox, oy)
        out.append(line)
    (dst / 'map.yaml').write_text('\n'.join(out) + '\n')
    np.save(dst / 'floor.npy', (np.load(src / 'floor.npy').astype(np.float32) - dz))

    with open(src / 'map.ply', 'rb') as f:
        header = []
        while True:
            line = f.readline()
            header.append(line)
            if line.strip() == b'end_header':
                break
        body = np.frombuffer(f.read(), '<f4').reshape(-1, 3).astype(np.float32)
    body = body - np.array([sx, sy, dz], np.float32)
    with open(dst / 'map.ply', 'wb') as f:
        f.writelines(header)
        f.write(body.astype('<f4').tobytes())

    (dst / 'SHIFT.json').write_text(json.dumps(dict(
        source=src.name, start_xy=[sx, sy], floor_at_start=floor0, lidar_h=a.lidar_h,
        shift_xyz=[-sx, -sy, -dz], points=int(len(body)),
        note='map frame moved so the LiDAR start pose is the origin and the floor is at -lidar_h'), indent=1))
    print('shifted', len(body), 'points into', dst, 'shift', [-sx, -sy, -round(dz, 3)])


if __name__ == '__main__':
    main()
