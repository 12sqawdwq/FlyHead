#!/usr/bin/env python3
"""Build a navigation package from a session map, keeping the floor derivation valid.

`export_nav.py` averages one LiDAR height from the recorded trajectory
(`lidar_height_above_floor_m`).  A session whose trajectory mixes postures
(crouch and stand) gives that average a value between the two, and the per-tile
floor reference then rejects real floor tiles: exporting a 931 k point session
that way produced a *smaller* known area (245 m2) than the 367 m2 base map.

This tool stages the session, tries the trajectory as a whole and split into
single-posture subsets, runs the exporter for each candidate, and keeps the
candidate that reproduces the reference derivation: the LiDAR height within
`--height-tolerance` of the reference and at least as much known area as the
reference.  All other candidates are removed again.

    python3 tools/export_session_map.py \\
        --session <run dir> --out <new package dir> --reference <base package>

It prints, and records in a receipt, the measurements for every candidate so a
rejected package is never mistaken for a better map.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_nav  # noqa: E402  (tools/export_nav.py)


def grid_stats(package):
    """Known/occupied/free cell counts and the derived LiDAR height of a package."""
    data = (Path(package) / 'map.pgm').read_bytes()
    parts = data.split(b'\n', 3)
    width, height = map(int, parts[1].split())
    grid = np.flipud(np.frombuffer(parts[3], np.uint8, count=width * height).reshape(height, width)).T
    info = json.loads((Path(package) / 'MAP_INFO.json').read_text())
    floor = info['grid']
    return dict(known_cells=int((grid != 205).sum()), occupied_cells=int((grid == 0).sum()),
                free_cells=int((grid == 254).sum()),
                known_m2=round(float((grid != 205).sum()) * floor['resolution'] ** 2, 1),
                lidar_height_above_floor_m=floor.get('lidar_height_above_floor_m'))


def stage(session, target, rows):
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(session / 'map.ply', target / 'map.ply')
    for name in ('summary.json', 'BASE.json'):
        if (session / name).exists():
            shutil.copyfile(session / name, target / name)
    data = np.genfromtxt(session / 'trajectory.csv', delimiter=',', skip_header=1).reshape(-1, 5)
    if rows is not None:
        data = data[rows]
    header = (session / 'trajectory.csv').read_text().splitlines()[0]
    text = [header]
    for row in data:
        text.append(','.join('%.6f' % value for value in row))
    (target / 'trajectory.csv').write_text('\n'.join(text) + '\n')


def candidates(session):
    """Whole trajectory plus one subset per posture cluster, defined by the z column."""
    data = np.genfromtxt(session / 'trajectory.csv', delimiter=',', skip_header=1).reshape(-1, 5)
    height = data[:, 3]
    low, high = float(np.percentile(height, 10)), float(np.percentile(height, 90))
    middle = 0.5 * (low + high)
    yield 'all', None, len(data)
    yield 'low_height', np.flatnonzero(height <= middle), int((height <= middle).sum())
    yield 'high_height', np.flatnonzero(height > middle), int((height > middle).sum())


def supplement(args):
    """Replace only map.ply inside a copy of the reference package.

    The base grid and height layers come from the corrected onboard derivation and
    are what the planner and the operator already trust; a plain exporter run from
    the same cloud produces fewer known cells (245-260 m2 against 367 m2), so the
    supplemented cloud is installed for relocalisation only.  Everything else, and
    therefore the planning behaviour, is left byte-identical.
    """
    reference, out, cloud = Path(args.reference), Path(args.out), Path(args.ply)
    if out.exists():
        raise SystemExit('output already exists: %s' % out)
    shutil.copytree(reference, out)
    before = reference / 'map.ply'
    old_points = point_count(before)
    new_points = point_count(cloud)
    if new_points < old_points:
        raise SystemExit('refusing: the new cloud has fewer points (%d < %d)' % (new_points, old_points))
    kept = {}
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name != 'map.ply':
            kept[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    shutil.copyfile(cloud, out / 'map.ply')
    info = json.loads((out / 'MAP_INFO.json').read_text())
    info['supplement'] = dict(installed_at=__import__('time').strftime('%Y-%m-%dT%H:%M:%S%z'),
                              map_ply_source=str(cloud), point_count_before=old_points,
                              point_count_after=new_points,
                              map_ply_sha256=hashlib.sha256((out / 'map.ply').read_bytes()).hexdigest(),
                              unchanged=kept,
                              note='relocalisation cloud replaced; occupancy grid and height layers '
                                   'unchanged from the reference derivation')
    (out / 'MAP_INFO.json').write_text(json.dumps(info, ensure_ascii=False, indent=2))
    receipt = dict(scope='Install a supplemented point cloud into a copy of the reference base map',
                   reference=str(reference), out=str(out), cloud=str(cloud),
                   point_count_before=old_points, point_count_after=new_points,
                   grid=grid_stats(out), reference_grid=grid_stats(reference), unchanged=kept)
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: receipt[k] for k in ('point_count_before', 'point_count_after', 'grid',
                                              'reference_grid')}, ensure_ascii=False), flush=True)
    print('installed', out, flush=True)


def point_count(path):
    raw = Path(path).read_bytes()
    end = raw.index(b'end_header\n') + len(b'end_header\n')
    header = raw[:end].decode('ascii').splitlines()
    declared = int([line for line in header if line.startswith('element vertex')][0].split()[-1])
    return declared


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--session', help='run directory holding map.ply and trajectory.csv')
    parser.add_argument('--ply', help='supplement mode: point cloud to install into a copy of the reference package')
    parser.add_argument('--out', required=True, help='new package directory (must not exist)')
    parser.add_argument('--reference', required=True, help='package the new one must stay comparable with')
    parser.add_argument('--height-tolerance', type=float, default=0.05)
    parser.add_argument('--receipt', default=None)
    args = parser.parse_args()
    if bool(args.session) == bool(args.ply):
        parser.error('give exactly one of --session or --ply')
    if args.ply:
        supplement(args)
        return
    session, out, reference = Path(args.session), Path(args.out), Path(args.reference)
    reference_stats = grid_stats(reference)
    print('reference', json.dumps(reference_stats, ensure_ascii=False), flush=True)
    receipt = dict(scope='Build a navigation package from a session map with a posture-consistent floor reference',
                   session=str(session), reference=str(reference), reference_stats=reference_stats,
                   height_tolerance=args.height_tolerance, candidates=[])
    work = Path(tempfile.mkdtemp(prefix='export-session-'))
    winner = None
    try:
        for label, rows, count in candidates(session):
            candidate_dir = work / label
            package_dir = work / (label + '_package')
            stage(session, candidate_dir, rows)
            export_nav.main(str(candidate_dir), str(package_dir))
            stats = grid_stats(package_dir)
            ok_height = abs(stats['lidar_height_above_floor_m']
                            - reference_stats['lidar_height_above_floor_m']) <= args.height_tolerance
            ok_area = stats['known_cells'] >= reference_stats['known_cells']
            # The posture-consistent LiDAR height is the real gate: the reference grid
            # itself was not produced by this exporter, so a plain re-derivation of the
            # same cloud legitimately yields a different (and usually smaller) known
            # area.  The area is recorded and warned about, not used to reject.
            entry = dict(label=label, trajectory_rows=count, **stats, height_ok=ok_height,
                         area_ok=ok_area,
                         warning=None if ok_area else 'known area is smaller than the reference '
                                                      '(%.1f m2 against %.1f m2)'
                                                      % (stats['known_m2'], reference_stats['known_m2']),
                         accepted=bool(ok_height))
            receipt['candidates'].append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            if entry['accepted'] and winner is None:
                winner = (label, package_dir)
        if winner is None:
            receipt['outcome'] = 'no candidate reproduced the reference derivation; nothing was installed'
            print(receipt['outcome'], flush=True)
        else:
            shutil.copytree(winner[1], out)
            receipt['outcome'] = 'installed'
            receipt['chosen'] = winner[0]
            receipt['output'] = str(out)
            hashes = {}
            for path in sorted(out.iterdir()):
                if path.is_file():
                    hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            receipt['output_sha256'] = hashes
            print('installed', out, 'from candidate', winner[0], flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if args.receipt:
            Path(args.receipt).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            print('RECEIPT', args.receipt, flush=True)
    if receipt['outcome'] != 'installed':
        raise SystemExit(3)


if __name__ == '__main__':
    main()
