"""Retina v3 evaluation on pass-A output (rates_v3/features_v3 computed from pooled world points)."""
import json, math, sys
S = [json.loads(l) for l in open(sys.argv[1])]
rows = []
for i in range(1, len(S)):
    s, a = S[i], S[i - 1]; dt = s['t'] - a['t']
    speed = math.hypot(s['pose'][0] - a['pose'][0], s['pose'][1] - a['pose'][1]) / dt if dt > 0 else 0
    yr = abs(math.remainder(s['pose'][2] - a['pose'][2], 2 * math.pi)) / dt if dt > 0 else 0
    f = s['features_v3']; r = s['rates_v3']
    rows.append((speed, yr, max(f['left']['loom_rad_s'], f['right']['loom_rad_s']), r, min(f['left']['nearest_m'], f['right']['nearest_m'])))
for name, sel in (('standing still', lambda r: r[0] < 0.03 and r[1] < 0.05), ('turning in place', lambda r: r[0] < 0.05 and r[1] > 0.1),
                  ('driving > 0.1 m/s', lambda r: r[0] > 0.1), ('driving, obstacle < 1 m', lambda r: r[0] > 0.1 and r[4] < 1.0),
                  ('driving, obstacle < 0.6 m', lambda r: r[0] > 0.1 and r[4] < 0.6)):
    sel = [r for r in rows if sel(r)]
    print('%-26s %5d scans | any loom %5.1f%% | loom > 0.15 rad/s %5.1f%%' % (name, len(sel), 100 * sum(r[2] > 0 for r in sel) / max(1, len(sel)), 100 * sum(r[2] > 0.15 for r in sel) / max(1, len(sel))))
print('LC4 at ceiling %.1f%% of scans' % (100 * sum(max(r[3]['LC4_left'], r[3]['LC4_right']) >= 199.9 for r in rows) / len(rows)))
