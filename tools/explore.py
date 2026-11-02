"""Exploratory timeline of a shadow segment (not a protocol criterion). python explore.py RUN T0 T1"""
import json, sys, collections
import numpy as np
run, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
R = [r for r in map(json.loads, open(run + '/brain_windows.jsonl')) if t0 <= r['window_start'] <= t1]
side = lambda r, s: sum(v for k, v in r['inputs_hz'].items() if k.startswith(('LC4_', 'LPLC2_')) and k.endswith(s))
hz = lambda r, k: r['readouts_hz'].get(k, 0)
print('windows %d, stale %.1f%%, brain p50 %.0f ms, age p50/p95 %.2f/%.2f' % (len(R), 100*np.mean([r['stale'] for r in R]),
      np.median([r['brain_ms'] for r in R]), *np.percentile([r['input_age_s'] for r in R if r['input_age_s'] is not None], [50, 95])))
print('states', collections.Counter(r['intent']['state'] for r in R).most_common())
print(' t(s)  loomL  loomR  LC9L  LC9R | GF_L GF_R  P9  MDN  DNa02R-L | state           v      w')
for i in range(0, len(R), 4):                      # ~0.5 s rows, only interesting ones
    g = R[i:i+4]; r = max(g, key=lambda r: max(side(r, 'left'), side(r, 'right')))
    st = [x['intent']['state'] for x in g]
    if max(side(r, 'left'), side(r, 'right')) < 40 and not any(s.startswith(('ESCAPE', 'BACK')) for s in st):
        continue
    lc9 = lambda s: r['inputs_hz'].get('LC9_' + s, 0)
    k = next((x for x in g if x['intent']['state'].startswith(('ESCAPE', 'BACK'))), r)
    print('%5.1f %6.0f %6.0f %5.0f %5.0f | %4.0f %4.0f %4.0f %4.0f %7.0f | %-14s %5.2f %6.2f' % (
        r['window_start'] - t0, side(r, 'left'), side(r, 'right'), lc9('left'), lc9('right'), hz(r, 'DNp01_left'), hz(r, 'DNp01_right'),
        hz(r, 'DNp09_left') + hz(r, 'DNp09_right'), sum(v for kk, v in r['readouts_hz'].items() if kk.startswith('MDN')),
        hz(r, 'DNa02_right') - hz(r, 'DNa02_left'), k['intent']['state'], k['intent']['v'], k['intent']['w']))
