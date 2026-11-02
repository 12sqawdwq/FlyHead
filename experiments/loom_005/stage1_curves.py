"""Stage 1: dose-response of descending neurons to the loom_005 inputs + window compute time.
Offline, no robot I/O. python stage1_curves.py OUT_DIR"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from brain import Brain  # noqa: E402
from retina import input_indices  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=False)
reg = json.loads((ROOT / 'config/loom_registry.json').read_text())
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
brain = Brain(reg, idx, ROOT / 'cache')
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
    res = dict(condition=name, inputs={'%s_%s' % k: v for k, v in spec.items()},
               on_rates_hz=mean_rates(on), off_rates_hz=mean_rates(off),
               on_all_spikes_per_window=int(np.mean([r[1] for r in on])))
    results.append(res)
    print(json.dumps({'condition': name, 'on': {k: v for k, v in res['on_rates_hz'].items() if v > 0}}), flush=True)
t = np.array(timings)
summary = dict(setup_s=round(setup_s, 1), window_s=brain.window_s, windows=len(t),
               ms_p50=round(float(np.percentile(t, 50)), 1), ms_p95=round(float(np.percentile(t, 95)), 1),
               ms_max=round(float(t.max()), 1), results=results)
(out / 'STAGE1_CURVES.json').write_text(json.dumps(summary, indent=1))
print('timing ms p50 %.1f p95 %.1f max %.1f (window %d ms), setup %.0f s' % (summary['ms_p50'], summary['ms_p95'], summary['ms_max'], brain.window_s * 1000, setup_s))
