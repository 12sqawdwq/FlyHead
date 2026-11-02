"""Create a fixed browser display asset from the saved XYZ navigation map.

This changes display density only, not the robot's map or navigation settings.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        required=True, help='map.ply of the map package to display')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'flyhead/monitor/web/navigation')
    parser.add_argument('--voxel', type=float, default=0.15)
    args = parser.parse_args()
    if not np.isfinite(args.voxel) or args.voxel <= 0:
        parser.error('--voxel must be a positive finite number')
    source = args.source.resolve()
    output = args.output.resolve()
    with source.open('rb') as stream:
        header = []
        while True:
            line = stream.readline()
            if not line:
                raise ValueError('PLY header has no end_header')
            text = line.decode('ascii').strip()
            header.append(text)
            if text == 'end_header':
                break
        expected_properties = ['property float x', 'property float y', 'property float z']
        properties = [line for line in header if line.startswith('property ')]
        if 'format binary_little_endian 1.0' not in header or properties != expected_properties:
            raise ValueError('Expected a binary little-endian PLY with float XYZ vertices')
        counts = [int(line.split()[2]) for line in header if line.startswith('element vertex ')]
        if len(counts) != 1:
            raise ValueError('Expected one vertex count')
        points = np.fromfile(stream, dtype='<f4', count=counts[0] * 3).reshape(-1, 3)
    if len(points) != counts[0] or not len(points) or not np.isfinite(points).all():
        raise ValueError('Invalid or incomplete map coordinates')
    keys = np.floor(points / args.voxel).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    display = np.ascontiguousarray(points[np.sort(indices)], dtype='<f4')
    output.mkdir(parents=True, exist_ok=True)
    display.tofile(output / 'map.bin')
    metadata = {
        'map': source.parent.name,
        'frame': 'xt_map',
        'source': str(source),
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'format': 'little-endian float32 XYZ',
        'points': len(display),
        'display_voxel_m': args.voxel,
        'bounds_min': display.min(axis=0).tolist(),
        'bounds_max': display.max(axis=0).tolist(),
        'live_updates': False,
    }
    (output / 'map.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print('Fixed display map: ' + str(output / 'map.bin'))
    print('Display metadata: ' + str(output / 'map.json'))
    print('Display points: %d' % len(display))


if __name__ == '__main__':
    main()
