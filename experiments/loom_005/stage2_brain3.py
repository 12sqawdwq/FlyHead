"""Stage 2 pass B, retina v3: stored pooled world ranges -> LidarRetinaV3 -> brain -> decoder.
Lockstep 100 ms windows; a window whose newest scan is older than STALE_SCAN_S gets no input.
python stage2_brain3.py RETINA_JSONL OUT_JSONL"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from brain import Brain  # noqa: E402
from decoder import decode  # noqa: E402
from retina import STALE_SCAN_S, LidarRetinaV3, input_indices, rates_vector, stale_rates  # noqa: E402

reg = json.loads((ROOT / 'config/loom_registry.json').read_text())
scans = [json.loads(l) for l in open(sys.argv[1])]
ret = LidarRetinaV3()
for s in scans:                                    # retina at scan time, in recording order
    s['r3'], s['f3'] = ret.step_world(s['features_v3']['world_ranges_m'], s['pose'][2], s['t'])
brain = Brain(reg, input_indices(reg), ROOT / 'cache')
out = open(sys.argv[2], 'w')
t, k, n = scans[0]['t'], 0, 0
while t <= scans[-1]['t']:
    while k + 1 < len(scans) and scans[k + 1]['t'] <= t:
        k += 1
    s = scans[k]
    stale = t - s['t'] > STALE_SCAN_S
    rates = stale_rates(s['r3']) if stale else s['r3']
    delta, all_spikes, ms = brain.step(rates_vector(reg, rates))
    hz = {kk: v / brain.window_s for kk, v in brain.readouts_by_type(delta).items()}
    row = dict(t=round(t, 2), scan_age_s=round(t - s['t'], 3), stale=stale, pose=s['pose'], fit=s['fit'], mode=s['mode'],
               inputs_hz={'%s_%s' % kk: round(v, 1) for kk, v in rates.items()},
               features={kk: v for kk, v in s['f3'].items() if kk != 'world_ranges_m'},
               readouts_hz={'%s_%s' % kk: round(v, 1) for kk, v in hz.items() if v}, all_spikes=all_spikes,
               brain_ms=round(ms, 1), intent=decode(hz), retina_version=3, live_admission=False)
    out.write(json.dumps(row) + chr(10)); n += 1
    if n % 1000 == 0:
        out.flush(); print('t %.0f windows %d' % (t, n), flush=True)
    t += brain.window_s
out.close()
print('done: %d windows' % n)
