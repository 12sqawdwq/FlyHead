"""Apply an operator's polygon draft to an independent, floor-preserving map package.

Requires NumPy. Never deploys, modifies the source package, or invents free-space
observations. Coordinates, grid geometry, floor reference, and trajectory stay fixed.
Only cells that lost obstacle points have their obstacle layers reconstructed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
from datetime import datetime, timezone
import zlib

import numpy as np


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_cloud(path):
    with path.open('rb') as stream:
        header = []
        for _ in range(1000):
            line = stream.readline()
            if not line:
                raise ValueError('Incomplete PLY header')
            header.append(line.decode('ascii').strip())
            if header[-1] == 'end_header':
                break
        else:
            raise ValueError('PLY header too long')
        properties = [line for line in header if line.startswith('property ')]
        elements = [line for line in header if line.startswith('element ')]
        if ('format binary_little_endian 1.0' not in header
                or properties != ['property float x', 'property float y', 'property float z']
                or len(elements) != 1 or not elements[0].startswith('element vertex ')):
            raise ValueError('Expected a binary little-endian XYZ-only vertex cloud')
        count = int(elements[0].split()[2])
        points = np.fromfile(stream, dtype='<f4')
    if count <= 0 or points.size != count * 3 or not np.isfinite(points).all():
        raise ValueError('Invalid PLY coordinates or payload length')
    return header, points.reshape(-1, 3)


def write_cloud(path, header, points):
    lines = [f'element vertex {len(points)}' if line.startswith('element vertex ') else line for line in header]
    with path.open('wb') as stream:
        stream.write(('\n'.join(lines) + '\n').encode('ascii'))
        np.asarray(points, dtype='<f4').tofile(stream)


def polygon_mask(points, vertices, z_min, z_max):
    vertices = np.asarray(vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or not 3 <= len(vertices) <= 128:
        raise ValueError('Invalid polygon shape')
    if not np.isfinite(vertices).all() or not np.isfinite([z_min, z_max]).all() or z_min >= z_max:
        raise ValueError('Invalid polygon coordinates or height range')
    low = vertices.min(axis=0)
    high = vertices.max(axis=0)
    candidates = np.flatnonzero(
        (points[:, 0] >= low[0]) & (points[:, 0] <= high[0])
        & (points[:, 1] >= low[1]) & (points[:, 1] <= high[1])
        & (points[:, 2] >= z_min) & (points[:, 2] <= z_max)
    )
    # Float64 arithmetic matches the browser's Number calculations at polygon edges.
    x = points[candidates, 0].astype(np.float64)
    y = points[candidates, 1].astype(np.float64)
    inside = np.zeros(len(candidates), dtype=bool)
    boundary = np.zeros(len(candidates), dtype=bool)
    for i, a in enumerate(vertices):
        b = vertices[(i + 1) % len(vertices)]
        cross = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
        boundary |= (
            (np.abs(cross) < 1e-8)
            & (x >= min(a[0], b[0]) - 1e-8) & (x <= max(a[0], b[0]) + 1e-8)
            & (y >= min(a[1], b[1]) - 1e-8) & (y <= max(a[1], b[1]) + 1e-8)
        )
        if a[1] != b[1]:
            inside ^= ((a[1] > y) != (b[1] > y)) & (x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0])
    mask = np.zeros(len(points), dtype=bool)
    mask[candidates[inside | boundary]] = True
    return mask


def read_grid(path):
    header, dimensions, maximum, payload = path.read_bytes().split(b'\n', 3)
    width, height = map(int, dimensions.split())
    if header != b'P5' or maximum != b'255' or len(payload) != width * height:
        raise ValueError('Unexpected PGM format')
    return np.flipud(np.frombuffer(payload, np.uint8).reshape(height, width)).T.copy()


def write_grid(path, grid):
    width, height = grid.shape
    path.write_bytes(f'P5\n{width} {height}\n255\n'.encode('ascii') + np.flipud(grid.T).tobytes())


def write_preview(path, grid):
    image = np.flipud(grid.T)
    height, width = image.shape
    raw = b''.join(b'\x00' + row.tobytes() for row in image)

    def chunk(kind, data):
        checksum = zlib.crc32(kind + data) & 0xffffffff
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', checksum)

    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draft', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--display', type=Path, required=True, help='Directory of the display map bound to the draft')
    parser.add_argument('--output', type=Path, required=True, help='New map package; must not exist')
    args = parser.parse_args()
    draft_path = args.draft.resolve()
    source = args.source.resolve()
    display = args.display.resolve()
    output = args.output.resolve()
    if output.exists() or source == output or source in output.parents:
        raise ValueError('Output must be a new independent directory outside the source package')
    draft = json.loads(draft_path.read_text(encoding='utf-8'))
    info = json.loads((source / 'MAP_INFO.json').read_text(encoding='utf-8'))
    display_info = json.loads((display / 'map.json').read_text(encoding='utf-8'))
    identity = draft['map_identity']
    if (draft.get('schema') != 'xingtian.map-correction-draft' or draft.get('version') != 1
            or draft.get('units') != 'metres' or draft.get('height_reference') != 'absolute_map_z'
            or not 1 <= len(draft.get('regions', [])) <= 64):
        raise ValueError('Unsupported correction draft')
    if (identity['map'] != source.name or identity['frame'] != info['frame']['name']
            or identity['source_sha256'] != sha256(source / 'map.ply')
            or identity['display_sha256'] != sha256(display / 'map.bin')
            or any(identity[key] != display_info[key] for key in ('map', 'frame', 'source_sha256'))):
        raise ValueError('Draft, source, and display identities do not match')
    header, points = read_cloud(source / 'map.ply')
    grid = read_grid(source / 'map.pgm')
    floor = np.load(source / 'floor.npy', allow_pickle=False)
    hmin = np.load(source / 'obst_hmin.npy', allow_pickle=False)
    hmax = np.load(source / 'obst_hmax.npy', allow_pickle=False)
    bins = np.load(source / 'obst_bins.npy', allow_pickle=False)
    if any(layer.shape != grid.shape for layer in (floor, hmin, hmax, bins)):
        raise ValueError('Grid and layer dimensions differ')
    # Preserve the exporter's exact origin (YAML is a rounded serialization).
    origin = np.asarray(info['grid']['origin'][:2], dtype=points.dtype)
    resolution = float(info['grid']['resolution'])
    ij = np.floor((points[:, :2] - origin) / resolution).astype(np.int64)
    if np.any(ij < 0) or np.any(ij >= np.asarray(grid.shape)):
        raise ValueError('Source points outside source grid')
    cell = ij[:, 0] * grid.shape[1] + ij[:, 1]
    above_floor = points[:, 2] - floor.ravel()[cell]
    band_low, band_high = info['grid']['obstacle_band_above_floor_m']
    eligible = np.isfinite(above_floor) & (above_floor > band_low)
    removed = np.zeros(len(points), dtype=bool)
    requested = np.zeros(len(points), dtype=bool)
    region_counts = []
    for region in draft['regions']:
        if region['operation'] != 'propose_clear_static_obstacle':
            raise ValueError('Unsupported region operation')
        selected = polygon_mask(points, region['polygon_xy_m'], region['z_min_m'], region['z_max_m'])
        deletion = selected & eligible
        requested |= selected
        removed |= deletion
        region_counts.append({
            'id': region['id'], 'name': region['name'],
            'selected_source_points': int(selected.sum()),
            'removed_obstacle_points': int(deletion.sum()),
            'protected_floor_or_unresolved_points': int((selected & ~eligible).sum()),
        })
    if not removed.any():
        raise ValueError('No eligible obstacle points selected; no package created')
    kept = ~removed
    touched = np.zeros(grid.size, dtype=bool)
    touched[np.unique(cell[removed])] = True
    counts = np.zeros(grid.size, dtype=np.int32)
    floors = np.zeros(grid.size, dtype=np.int32)
    np.add.at(counts, cell[kept & (above_floor > band_low) & (above_floor < band_high)], 1)
    tolerance = info['grid']['floor_tolerance_m']
    np.add.at(floors, cell[kept & (np.abs(above_floor) < tolerance)], 1)
    # Conservative local reconstruction: no morphology across the ROI boundary and
    # no newly free cells without retained, observed floor returns at that cell.
    old_grid = grid.copy()
    edited = grid.ravel()
    edited[touched] = 205
    edited[touched & ((old_grid.ravel() == 254) | (floors > 0))] = 254
    edited[touched & (counts > 0)] = 0
    edited[touched & (old_grid.ravel() == 205) & (counts == 0)] = 205
    height_config = info['height_layers']
    bin_config = height_config['bins']
    bin_count = int(bin_config['count'])
    if bin_count != 16 or bins.dtype != np.uint16:
        raise ValueError('Expected 16-bin uint16 height layers')
    tall = kept & touched[cell] & (above_floor > band_low) & (above_floor < height_config['max_height_m'])
    new_min = np.full(grid.size, np.inf, dtype=np.float32)
    new_max = np.full(grid.size, -np.inf, dtype=np.float32)
    np.minimum.at(new_min, cell[tall], above_floor[tall])
    np.maximum.at(new_max, cell[tall], above_floor[tall])
    hmin.ravel()[touched] = new_min[touched]
    hmax.ravel()[touched] = new_max[touched]
    bin_indices = np.clip(((above_floor[tall] - bin_config['base_m']) / bin_config['height_m']).astype(int), 0, bin_count - 1)
    bin_counts = np.zeros((grid.size, bin_count), dtype=np.uint32)
    np.add.at(bin_counts, (cell[tall], bin_indices), 1)
    new_bits = ((bin_counts >= bin_config['min_points']).astype(np.uint32) << np.arange(bin_count, dtype=np.uint32)).sum(axis=1)
    bins.ravel()[touched] = new_bits[touched].astype(np.uint16)
    input_names = ['map.ply', 'map.pgm', 'map.yaml', 'MAP_INFO.json', 'floor.npy', 'obst_hmin.npy', 'obst_hmax.npy', 'obst_bins.npy', 'trajectory.csv']
    input_hashes = {name: sha256(source / name) for name in input_names}
    output.mkdir(parents=True, exist_ok=False)
    write_cloud(output / 'map.ply', header, points[kept])
    write_cloud(output / 'removed_points.ply', header, points[removed])
    write_grid(output / 'map.pgm', grid)
    write_preview(output / 'map_preview.png', grid)
    for name in ('map.yaml', 'floor.npy', 'trajectory.csv'):
        shutil.copyfile(source / name, output / name)
    for name, layer in (('obst_hmin.npy', hmin), ('obst_hmax.npy', hmax), ('obst_bins.npy', bins)):
        np.save(output / name, layer)
    shutil.copyfile(draft_path, output / 'correction_draft.json')
    summary = {
        'status': 'LOCAL_MANUAL_CORRECTION__NOT_DEPLOYED',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source': str(source), 'output': str(output),
        'draft_sha256': sha256(draft_path),
        'tool_sha256': sha256(Path(__file__).resolve()),
        'source_hashes': input_hashes,
        'regions': region_counts,
        'source_points': len(points), 'retained_points': int(kept.sum()),
        'removed_points': int(removed.sum()),
        'protected_selected_points': int((requested & ~eligible).sum()),
        'edited_cells': int(touched.sum()),
        'occupied_to_free_cells': int(((old_grid == 0) & (grid == 254)).sum()),
        'occupied_to_unknown_cells': int(((old_grid == 0) & (grid == 205)).sum()),
        'source_draft_status': draft.get('status'),
        'live_clearance_evidence': 'not_collected',
        'policy': 'Remove selected points only above preserved local floor + obstacle-band lower limit; preserve unknown cells and all untouched cells. Retained obstacle returns block touched cells conservatively.',
        'validation': 'No separate post-generation validation or navigation/localization evaluation performed.',
        'deployment': 'none; current browser display and robot package unchanged',
    }
    # Do not attribute the historical source run's metrics to the new cloud.
    info['parent_map'] = {'path': str(source), 'sha256': input_hashes['MAP_INFO.json']}
    info['created'] = summary['created_at']
    info['cloud']['points'] = int(kept.sum())
    info['slam'].pop('last_session_summary', None)
    info['lineage'].append('Operator ROI cleanup; see correction.json for exact provenance and scope')
    info['grid']['occupied_cells'] = int((grid == 0).sum())
    info['grid']['free_cells'] = int((grid == 254).sum())
    info['grid']['unknown_cells'] = int((grid == 205).sum())
    info['grid']['correction_policy'] = summary['policy']
    info['caveats'].append('Manual ROI obstacle removal, not live-verified free space; no robot deployment or motion acceptance.')
    (output / 'MAP_INFO.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    summary['output_hashes'] = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file()}
    (output / 'correction.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
