"""Stage 2 pass B: retina rows -> brain -> decoder, lockstep 100 ms neural windows (brain env).
python stage2_brain.py RETINA_JSONL OUT_JSONL"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from brain import Brain  # noqa: E402
from decoder import decode  # noqa: E402
from retina import input_indices, rates_vector  # noqa: E402

reg = json.loads((ROOT / 'config/loom_registry.json').read_text())
scans = [json.loads(l) for l in open(sys.argv[1])]
brain = Brain(reg, input_indices(reg), ROOT / 'cache')
out = open(sys.argv[2], 'w')
t, k, n = scans[0]['t'], 0, 0
while t <= scans[-1]['t']:
    while k + 1 < len(scans) and scans[k + 1]['t'] <= t:     # latest scan at the window start
        k += 1
    s = scans[k]
    rates = {tuple(key.rsplit('_', 1)): v for key, v in s['rates'].items()}
    delta, all_spikes, ms = brain.step(rates_vector(reg, rates))
    hz = {kk: v / brain.window_s for kk, v in brain.readouts_by_type(delta).items()}
    row = dict(t=round(t, 2), scan_t=s['t'], scan_age_s=round(t - s['t'], 3), pose=s['pose'], fit=s['fit'], mode=s['mode'],
               inputs_hz=s['rates'], features={kk: v for kk, v in s['features'].items() if kk != 'ranges_m'},
               readouts_hz={'%s_%s' % kk: round(v, 1) for kk, v in hz.items() if v}, all_spikes=all_spikes,
               brain_ms=round(ms, 1), intent=decode(hz), live_admission=False)
    out.write(json.dumps(row) + '\n'); n += 1
    if n % 500 == 0:
        out.flush(); print('t %.0f windows %d brain_ms %.0f state %s' % (t, n, ms, row['intent']['state']), flush=True)
    t += brain.window_s
out.close()
print('done: %d windows' % n)
