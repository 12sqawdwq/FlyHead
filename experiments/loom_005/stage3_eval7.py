"""Evaluate a decoder-v7 stage 3 run against PROTOCOL_STAGE3.md amendment 6. python stage3_eval7.py RUN_DIR"""
import json
import math
import sys
from pathlib import Path

run = Path(sys.argv[1])
load = lambda name: [json.loads(l) for l in open(run / ('%s_brain.jsonl' % name))]
results = []
DEFENCE = ('FREEZE', 'ESCAPE_PROGRAM', 'BACK_OFF')


def row(cid, name, ok, detail):
    results.append(dict(id=cid, scenario=name, passed=bool(ok), detail=detail))
    print('%-3s %-13s %s  %s' % (cid, name, 'PASS' if ok else 'FAIL', detail))


def bouts(R, state):
    out, start = [], None
    for r in R:
        if r['intent']['state'] == state and start is None:
            start = r['t']
        elif r['intent']['state'] != state and start is not None:
            out.append(round(r['t'] - start, 1)); start = None
    if start is not None:
        out.append(round(R[-1]['t'] - start, 1))
    return out


def onsets(R):
    """Starts of a defensive episode (FREEZE or ESCAPE_PROGRAM entered from another state)."""
    n, prev = 0, None
    for r in R:
        s = r['intent']['state']
        if s in ('FREEZE', 'ESCAPE_PROGRAM') and prev not in ('FREEZE', 'ESCAPE_PROGRAM'):
            n += 1
        prev = s
    return n


R = load('wall_ahead')
contacts = sum(r['contact'] for r in R); over = 100 * sum(bool(r['envelope']) for r in R) / len(R)
clear = min(r['clearance'] for r in R)
row('C1', 'wall_ahead', contacts == 0 and over <= 10 and clear >= 0.50,
    'contacts %d, overrides %.1f%%, min clearance %.2f m' % (contacts, over, clear))
R = load('roam_open')
contacts = sum(r['contact'] for r in R); n = onsets(R)
rest = bouts(R, 'REST')
row('C2', 'roam_open', contacts == 0 and n <= 3,
    'contacts %d, defensive onsets %d; REST %.0f%% of windows, bouts %s s; FLEE bouts %s s' % (
        contacts, n, 100 * sum(r['intent']['state'] == 'REST' for r in R) / len(R), rest, bouts(R, 'FLEE')))
for name in ('person_front', 'person_left', 'person_right'):
    R = load(name)
    contacts = sum(r['contact'] for r in R)
    onset = next((r for r in R if max(r['loom']) > 0.05), None)
    if onset is None:
        row('C3', name, False, 'no loom onset'); continue
    react = next((r for r in R if r['t'] >= onset['t'] and r['intent']['state'] in DEFENCE), None)
    latency = None if react is None else round(react['t'] - onset['t'], 1)
    dist = lambda r: math.hypot(r['x'] - r['objects'][0][0], r['y'] - r['objects'][0][1])
    esc = next((r for r in R if r['t'] >= onset['t'] and r['intent']['state'] == 'ESCAPE_PROGRAM'), None)
    if esc is not None:
        later = next((r for r in R if r['t'] >= esc['t'] + 3.0), R[-1])
        gained = dist(later) > dist(esc)
        what = 'escape at %.1f s, distance %.2f -> %.2f m 3 s later' % (esc['t'] - onset['t'], dist(esc), dist(later))
    else:
        gained, what = True, 'no escape (freeze/stay)'
    later0 = next((r for r in R if r['t'] >= onset['t'] + 3.0), R[-1])
    row('C3', name, contacts == 0 and latency is not None and latency <= 1.0 and gained,
        'contacts %d, first response %s after %s s; %s; [v6 metric: %.2f -> %.2f m 3 s after onset]; FREEZE %s s, FLEE %s s' % (
            contacts, react and react['intent']['state'], latency, what, dist(onset), dist(later0), bouts(R, 'FREEZE'), bouts(R, 'FLEE')))
passed = all(r['passed'] for r in results)
(run / 'STAGE3_RESULT.json').write_text(json.dumps(dict(passed=passed, rows=results), indent=1))
print('STAGE 3', 'PASSED' if passed else 'FAILED')
