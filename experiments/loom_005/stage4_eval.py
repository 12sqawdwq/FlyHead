"""Evaluate stage 4 (shadow) against PROTOCOL_STAGE4.md.
python stage4_eval.py RUN_DIR T0 [T_END]   (server-clock seconds; T0 = shadow start)
Approach episodes are found from the loom inputs: an episode starts at the first window whose
LC4+LPLC2 input on one side is >= EPISODE_HZ and ends after 3 s below it (still-scene flicker is 5-17 Hz). The operator's trial order
(front x3, left x3, right x3) labels them; the loom side seen by the retina is reported separately.
"""
import json
import sys
from pathlib import Path

import numpy as np

run = Path(sys.argv[1]); t0 = float(sys.argv[2]); t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 1e18
R = [r for r in map(json.loads, open(run / 'brain_windows.jsonl')) if t0 <= r['window_start'] <= t1]
EPISODE_HZ = 40.0
REACT = ('ESCAPE', 'ESCAPE_PROGRAM', 'BACK_OFF')
loom = lambda r, side: sum(v for k, v in r['inputs_hz'].items() if k.startswith(('LC4_', 'LPLC2_')) and k.endswith(side))
ms = np.array([r['brain_ms'] for r in R]); age = np.array([r['input_age_s'] for r in R if r['input_age_s'] is not None])
stale = 100 * np.mean([r['stale'] for r in R])
print('M1 windows %d over %.0f s; brain %.0f/%.0f ms p50/p95; input age %.2f/%.2f s; stale %.1f %%'
      % (len(R), R[-1]['window_start'] - R[0]['window_start'], *np.percentile(ms, [50, 95]), *np.percentile(age, [50, 95]), stale))
esc = 100 * np.mean([r['intent']['state'] in REACT[:2] for r in R])
print('M3 ESCAPE in %.1f %% of windows in this interval' % esc)
episodes, cur, last_on = [], None, -1e9
for r in R:
    on = max(loom(r, 'left'), loom(r, 'right')) >= EPISODE_HZ
    t = r['window_start']
    if on:
        if cur is None:                     # the previous episode ended >= 3 s after its last loom
            cur = dict(start=t, rows=[])
            episodes.append(cur)
        last_on = t
    if cur is not None:
        cur['rows'].append(r)
        if not on and t - last_on >= 3.0:
            cur = None
results = []
for i, e in enumerate(episodes):
    rows = e['rows']
    left = sum(loom(r, 'left') for r in rows); right = sum(loom(r, 'right') for r in rows)
    react = next((r for r in rows if r['intent']['state'] in REACT and r['window_start'] - e['start'] <= 1.0), None)
    first = next((r for r in rows if r['intent']['state'] in REACT), None)
    w = None if first is None else first['intent']['w']
    away = None if w is None or left == right else ((w < 0) if left > right else (w > 0))
    row = dict(episode=i + 1, t=round(e['start'] - t0, 1), duration_s=round(rows[-1]['window_start'] - e['start'], 1),
               loom_side='left' if left > 1.5 * right else 'right' if right > 1.5 * left else 'both',
               reaction_s=None if first is None else round(first['window_start'] - e['start'], 2), within_1s=react is not None,
               first_state=None if first is None else first['intent']['state'], turn_w=w, turn_away=away)
    results.append(row); print('M2', row)
(run / 'STAGE4_EPISODES.json').write_text(json.dumps(dict(t0=t0, t1=t1, episodes=results), indent=1))
