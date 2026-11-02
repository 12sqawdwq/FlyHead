"""Summarise sim_brain runs: contacts, clearance, envelope overrides, behaviour states, loom responses."""
import json, sys, collections
for path in sys.argv[1:]:
    R = [json.loads(l) for l in open(path)]
    states = collections.Counter(r['intent']['state'] for r in R)
    over = [r for r in R if r['envelope']]
    moved = sum(abs(r['v']) * 0.1 for r in R)
    loom_on = next((r['t'] for r in R if max(r['loom']) > 0.05), None)
    first_react = next((r['t'] for r in R if loom_on is not None and r['t'] >= loom_on and r['intent']['state'] in ('ESCAPE', 'BACK_OFF', 'TURN_LEFT', 'TURN_RIGHT')), None)
    ms = [r['brain_ms'] for r in R if r['brain_ms']]
    print('%-34s %4.0f s | contacts %3d | min clearance %.2f m | moved %5.1f m | envelope overrides %4.1f%% | states %s | first loom %s s -> first reaction %s s | brain ms p50 %s'
          % (path.split('/')[-1], R[-1]['t'], sum(r['contact'] for r in R), min(r['clearance'] for r in R), moved,
             100 * len(over) / len(R), dict(states.most_common(5)), loom_on, first_react,
             round(sorted(ms)[len(ms) // 2]) if ms else '-'))
