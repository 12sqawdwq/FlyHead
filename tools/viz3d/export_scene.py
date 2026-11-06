"""Export one closed-loop simulation scenario for the 3D renderer (tools/viz3d/render.html).

  python tools/viz3d/export_scene.py SCENARIO --runs DIR --map PKG [--out tools/viz3d/data]

Reads DIR/SCENARIO_brain.jsonl and DIR/SCENARIO_blind.jsonl (flyhead.sim.loom_sim records, one per 100 ms window)
and the map package the simulation ran on (PKG/map.ply, the saved SLAM cloud of the real site). Writes
OUT/SCENARIO.json with
  cloud   the site cloud within 14 m of the scenario, floor to 2 m above it (like the console), int16 centimetres
          in the renderer's axes (x, z up, -y)
  brain   per window: t, x, y, yaw, decoded state, executed v and w, clearance, loom L / R, LC9 L / R input rates,
          GF / MDN / P9 rates, descending-neuron readouts, envelope note
  blind   per window: t, x, y, yaw, executed v, w (the same scenario without the brain: drives straight)
  objects per window: object positions (cylinders of radius 0.25 m in the simulation)
Nothing is re-simulated or smoothed: the renderer interpolates between recorded windows for display only.
SCENARIO stage6 reads DIR/reflex_1.jsonl and DIR/planner_1.jsonl (flyhead.sim.reflex_sim) instead.
"""
import argparse
import base64
import json
import math
from pathlib import Path

import numpy as np

REACH_M = 14.0
CEILING_M = 2.0
OBJECT_RADIUS_M = 0.25        # flyhead.sim.loom_sim: every scenario object is a 0.25 m cylinder


def load(path):
    return [json.loads(line) for line in open(path, encoding='utf-8') if line.strip()]


def b64_int16(a):
    return base64.b64encode(np.asarray(a, '<i2').tobytes()).decode('ascii')


def b64_uint8(a):
    return base64.b64encode(np.asarray(a, 'u1').tobytes()).decode('ascii')


def cloud(pkg, cx, cy):
    from flyhead.slam.reloc import load_points
    p = load_points(Path(pkg) / 'map.ply')
    near = np.hypot(p[:, 0] - cx, p[:, 1] - cy)
    local = p[near < 2.5]
    floor = float(np.percentile(local[:, 2], 3)) if len(local) > 50 else float(np.percentile(p[:, 2], 2))
    keep = (near < REACH_M) & (p[:, 2] > floor - 0.15) & (p[:, 2] < floor + CEILING_M)
    p = p[keep]
    if len(p) > 260000:
        p = p[np.random.default_rng(0).choice(len(p), 260000, replace=False)]
    h = np.clip((p[:, 2] - floor) / CEILING_M, 0, 1)
    xyz = np.c_[p[:, 0], p[:, 2] - floor, -p[:, 1]]            # renderer axes: y up, floor at 0
    return dict(n=len(p), pos=b64_int16(np.round(xyz * 100).ravel()), h=b64_uint8(np.round(h * 255))), floor


def reflex_scene(a):
    """Stage 6: planner + fly reflexes. `brain` = reflex arm, `blind` = planner arm (brain in shadow), same seed and
    person. Extra per window: command source, navigator state, reflex takeovers, distance to the person."""
    def rows(path):
        R = load(path)
        return [r for r in R if 't' in r and 'type' not in r], next((r for r in R if r.get('type') == 'setup'), {})
    Rf, setup = rows(Path(a.runs) / 'reflex_1.jsonl')
    Pl, _ = rows(Path(a.runs) / 'planner_1.jsonl')
    c, floor = cloud(a.map, Rf[0]['x'], Rf[0]['y'])
    brain = [[round(r['t'], 2), round(r['x'], 3), round(r['y'], 3), round(r['yaw'], 4), r.get('brain_state') or '',
              round(r['cmd'][0], 3), round(r['cmd'][1], 3), round(r.get('wall_m') or 0, 3), 0, 0, 0, 0, 0, 0, 0, {}, '',
              bool(r.get('contact'))] for r in Rf]
    blind = [[round(r['t'], 2), round(r['x'], 3), round(r['y'], 3), round(r['yaw'], 4), round(r['cmd'][0], 3),
              round(r['cmd'][1], 3), bool(r.get('contact'))] for r in Pl]
    extra = [[r.get('source'), r.get('nav_state'), r.get('reflex_count') or 0,
              None if r.get('person_m') is None else round(r['person_m'], 2)] for r in Rf]
    objects = []
    for i, r in enumerate(Rf):
        q = Pl[min(i, len(Pl) - 1)]
        objects.append([None if r.get('person') is None else [round(v, 3) for v in r['person']],
                        None if q.get('person') is None else [round(v, 3) for v in q['person']]])
    scene = dict(scenario='stage6_planner_vs_reflex', mode='reflex', floor_z=round(floor, 3), object_radius=OBJECT_RADIUS_M,
                 decoder=9, goal=setup.get('goal'), cloud=c, brain=brain, blind=blind, objects=objects, extra=extra,
                 source=dict(reflex='reflex_1.jsonl', planner='planner_1.jsonl', map=str(Path(a.map) / 'map.ply')))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'stage6_planner_vs_reflex.json'
    path.write_text(json.dumps(scene, separators=(',', ':')))
    print('stage6: reflex %d windows, planner %d, goal %s -> %s' % (len(brain), len(blind), setup.get('goal'), path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('scenario')
    ap.add_argument('--runs', required=True)
    ap.add_argument('--map', required=True)
    ap.add_argument('--out', default=str(Path(__file__).parent / 'data'))
    a = ap.parse_args()
    if a.scenario == 'stage6':
        return reflex_scene(a)
    B = load(Path(a.runs) / f'{a.scenario}_brain.jsonl')
    blind_path = Path(a.runs) / f'{a.scenario}_blind.jsonl'
    N = load(blind_path) if blind_path.exists() else []
    c, floor = cloud(a.map, B[0]['x'], B[0]['y'])
    brain = []
    for r in B:
        it = r.get('intent') or {}
        inp, rd, loom = r.get('inputs') or {}, r.get('readouts') or {}, r.get('loom') or [0, 0]
        brain.append([round(r['t'], 2), round(r['x'], 3), round(r['y'], 3), round(r['yaw'], 4), it.get('state', ''),
                      round(r['executed'][0], 3), round(r['executed'][1], 3), round(r.get('clearance') or 0, 3),
                      round(loom[0], 3), round(loom[1], 3), round(inp.get('LC9_left', 0), 1), round(inp.get('LC9_right', 0), 1),
                      it.get('gf_hz', 0), it.get('mdn_hz', 0), it.get('p9_hz', 0),
                      {k: v for k, v in rd.items()}, r.get('envelope') or '', bool(r.get('contact'))])
    blind = [[round(r['t'], 2), round(r['x'], 3), round(r['y'], 3), round(r['yaw'], 4),
              round(r['executed'][0], 3), round(r['executed'][1], 3), bool(r.get('contact'))] for r in N]
    objects = [[[round(o[0], 3), round(o[1], 3)] for o in (r.get('objects') or [])] for r in B]
    scene = dict(scenario=a.scenario, floor_z=round(floor, 3), object_radius=OBJECT_RADIUS_M,
                 fields_brain=['t', 'x', 'y', 'yaw', 'state', 'v', 'w', 'clearance', 'loom_l', 'loom_r', 'lc9_l', 'lc9_r',
                               'gf', 'mdn', 'p9', 'readouts', 'envelope', 'contact'],
                 fields_blind=['t', 'x', 'y', 'yaw', 'v', 'w', 'contact'],
                 decoder=(B[0].get('intent') or {}).get('decoder_version'),
                 source=dict(brain=str(Path(a.runs) / f'{a.scenario}_brain.jsonl'), blind=str(blind_path) if N else None,
                             map=str(Path(a.map) / 'map.ply')),
                 cloud=c, brain=brain, blind=blind, objects=objects)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'{a.scenario}.json'
    path.write_text(json.dumps(scene, separators=(',', ':')))
    print('%s: %d windows (%.1f s), blind %d, cloud %d points, floor %.2f m -> %s (%.1f MB)' % (
        a.scenario, len(brain), brain[-1][0] - brain[0][0], len(blind), c['n'], floor, path, path.stat().st_size / 1e6))


if __name__ == '__main__':
    main()
