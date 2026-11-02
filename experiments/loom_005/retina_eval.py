"""Retina-only evaluation on recorded scans (pass A output): false loom while still vs loom while driving.
python retina_eval.py RETINA_JSONL"""
import json, math, sys
from retina import LidarRetinaV2, STALE_SCAN_S
S = [json.loads(l) for l in open(sys.argv[1])]
ret = LidarRetinaV2()
rows = []
for i, s in enumerate(S):
    rates, f = ret.step_ranges(s['features']['ranges_m'], s['pose'][2], s['t'])
    if i:
        a, dt = S[i - 1], s['t'] - S[i - 1]['t']
        speed = math.hypot(s['pose'][0] - a['pose'][0], s['pose'][1] - a['pose'][1]) / dt if dt > 0 else 0
        yr = abs(math.remainder(s['pose'][2] - a['pose'][2], 2 * math.pi)) / dt if dt > 0 else 0
        rows.append((speed, yr, max(f['left']['loom_rad_s'], f['right']['loom_rad_s']), rates, min(f['left']['nearest_m'], f['right']['nearest_m']), dt))
n = len(rows)
def pct(sel, cond):
    sel = [r for r in rows if sel(r)]
    return len(sel), 100 * sum(cond(r) for r in sel) / max(1, len(sel))
for name, sel in (('standing still', lambda r: r[0] < 0.03 and r[1] < 0.05), ('turning in place', lambda r: r[0] < 0.05 and r[1] > 0.1),
                  ('driving > 0.1 m/s', lambda r: r[0] > 0.1), ('driving with obstacle < 1 m', lambda r: r[0] > 0.1 and r[4] < 1.0)):
    k, p = pct(sel, lambda r: r[2] > 0.0)
    print('%-28s %5d scans | any loom %5.1f%%' % (name, k, p))
sat = 100 * sum(max(r[3][('LC4', 'left')], r[3][('LC4', 'right')]) >= 199.9 for r in rows) / n
print('LC4 at ceiling in %.1f%% of scans; scans with a gap > %.1f s: %d' % (sat, STALE_SCAN_S, sum(r[5] > STALE_SCAN_S for r in rows)))
