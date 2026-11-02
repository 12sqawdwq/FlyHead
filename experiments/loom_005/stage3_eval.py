"""Evaluate stage3_002 against PROTOCOL_STAGE3.md. python stage3_eval.py RUN_DIR"""
import json
import math
import sys
from pathlib import Path

run = Path(sys.argv[1])
load = lambda name: [json.loads(l) for l in open(run / ('%s_brain.jsonl' % name))]
results = []


def row(cid, name, ok, detail):
    results.append(dict(id=cid, scenario=name, passed=bool(ok), detail=detail))
    print('%-3s %-13s %s  %s' % (cid, name, 'PASS' if ok else 'FAIL', detail))


R = load('wall_ahead')
contacts = sum(r['contact'] for r in R); over = 100 * sum(bool(r['envelope']) for r in R) / len(R)
clear = min(r['clearance'] for r in R)
row('C1', 'wall_ahead', contacts == 0 and over <= 10 and clear >= 0.50,
    'contacts %d, overrides %.1f%%, min clearance %.2f m' % (contacts, over, clear))
R = load('roam_open')
contacts = sum(r['contact'] for r in R); esc = 100 * sum(r['intent']['state'] in ('ESCAPE', 'ESCAPE_PROGRAM') for r in R) / len(R)
row('C2', 'roam_open', contacts == 0 and esc <= 3, 'contacts %d, ESCAPE %.1f%% of windows' % (contacts, esc))
for name in ('person_front', 'person_left', 'person_right'):
    R = load(name)
    contacts = sum(r['contact'] for r in R)
    onset = next((r for r in R if max(r['loom']) > 0.05), None)
    if onset is None:
        row('C3', name, False, 'no loom onset'); continue
    react = next((r for r in R if r['t'] >= onset['t'] and r['intent']['state'] in ('ESCAPE', 'ESCAPE_PROGRAM', 'BACK_OFF')), None)
    latency = None if react is None else round(react['t'] - onset['t'], 1)
    dist = lambda r: math.hypot(r['x'] - r['objects'][0][0], r['y'] - r['objects'][0][1])
    later = next((r for r in R if r['t'] >= onset['t'] + 3.0), R[-1])
    farther = dist(later) > dist(onset)
    row('C3', name, contacts == 0 and latency is not None and latency <= 1.0 and farther,
        'contacts %d, reaction %s s after onset, distance to person %.2f -> %.2f m' % (contacts, latency, dist(onset), dist(later)))
passed = all(r['passed'] for r in results)
(run / 'STAGE3_RESULT.json').write_text(json.dumps(dict(passed=passed, rows=results), indent=1))
print('STAGE 3', 'PASSED' if passed else 'FAILED')
