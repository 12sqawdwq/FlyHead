"""Reproduce loom_005 stage 1 (dose response) with the maintained package and compare it with
the archived record experiments/loom_005/runs/stage1_001/STAGE1_CURVES.json.

Same conditions, order, seed and window length as experiments/loom_005/stage1_curves.py.
Needs a CUDA GPU and scripts/fetch_upstream.py. python tools/repro_stage1.py OUT_DIR
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from flyhead import paths
from flyhead.fly.encoders.lidar_loom import input_indices
from flyhead.fly.model import Brain

ARCHIVED = paths.REPO / 'experiments/loom_005/runs/stage1_001/STAGE1_CURVES.json'

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=False)
reg = paths.load_registry()
idx = input_indices(reg)
cells = [(t, c['anatomical_side']) for t in ('LC4', 'LPLC2', 'LC9') for c in reg['inputs'][t]]


def vec(spec):
    return np.array([spec.get(c, 0.0) for c in cells], dtype=np.float32)


CONDITIONS = [('zero', {})]
for hz in (30, 60, 120):
    CONDITIONS.append(('LC9_both_%d' % hz, {('LC9', 'left'): hz, ('LC9', 'right'): hz}))
for side in ('left', 'right'):
    for hz in (50, 100, 200):
        CONDITIONS.append(('LC4_%s_%d' % (side, hz), {('LC4', side): hz}))
    CONDITIONS.append(('LPLC2_%s_200' % side, {('LPLC2', side): 200}))
    CONDITIONS.append(('LC4+LPLC2_%s_200' % side, {('LC4', side): 200, ('LPLC2', side): 200}))
    CONDITIONS.append(('LC9_120+loom_%s_200' % side, {('LC9', 'left'): 120, ('LC9', 'right'): 120,
                                                       ('LC4', side): 200, ('LPLC2', side): 200}))
CONDITIONS.append(('loom_both_200', {('LC4', 'left'): 200, ('LC4', 'right'): 200, ('LPLC2', 'left'): 200, ('LPLC2', 'right'): 200}))

t0 = time.perf_counter()
brain = Brain(reg, idx)
setup_s = time.perf_counter() - t0
results, timings = [], []
for name, spec in CONDITIONS:
    on, off = [], []
    for k in range(15):                         # 10 windows on (1.0 s), 5 windows off (0.5 s)
        delta, all_spikes, ms = brain.step(vec(spec) if k < 10 else vec({}))
        timings.append(ms)
        (on if k < 10 else off).append((brain.readouts_by_type(delta), all_spikes))

    def mean_rates(rows):
        keys = rows[0][0].keys()
        return {'%s_%s' % k: round(sum(r[0][k] for r in rows) / (len(rows) * brain.window_s), 1) for k in keys}
    results.append(dict(condition=name, inputs={'%s_%s' % k: v for k, v in spec.items()},
                        on_rates_hz=mean_rates(on), off_rates_hz=mean_rates(off),
                        on_all_spikes_per_window=int(np.mean([r[1] for r in on]))))
t = np.array(timings)
summary = dict(setup_s=round(setup_s, 1), window_s=brain.window_s, windows=len(t),
               ms_p50=round(float(np.percentile(t, 50)), 1), ms_p95=round(float(np.percentile(t, 95)), 1),
               ms_max=round(float(t.max()), 1), results=results)
(out / 'STAGE1_CURVES.json').write_text(json.dumps(summary, indent=1))

old = {r['condition']: r for r in json.loads(ARCHIVED.read_text())['results']}
diffs, compared = [], 0
for r in results:
    a = old[r['condition']]
    for part in ('on_rates_hz', 'off_rates_hz'):
        for k, v in r[part].items():
            compared += 1
            if a[part].get(k) != v:
                diffs.append((r['condition'], part, k, a[part].get(k), v))
    compared += 1
    if a['on_all_spikes_per_window'] != r['on_all_spikes_per_window']:
        diffs.append((r['condition'], 'on_all_spikes_per_window', '', a['on_all_spikes_per_window'], r['on_all_spikes_per_window']))
max_abs = max((abs(d[4] - d[3]) for d in diffs if d[2]), default=0.0)
report = dict(compared_values=compared, differing=len(diffs), max_abs_rate_diff_hz=max_abs,
              identical=not diffs, ms_p50=summary['ms_p50'], ms_p95=summary['ms_p95'], diffs=diffs[:40])
(out / 'COMPARE.json').write_text(json.dumps(report, indent=1))
print(json.dumps({k: v for k, v in report.items() if k != 'diffs'}))
for d in diffs[:15]:
    print('DIFF', *d)
