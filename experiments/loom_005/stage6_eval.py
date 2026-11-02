"""Evaluate stage 6 simulation runs against PROTOCOL_STAGE6.md. python stage6_eval.py RUN_DIR"""
import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
rows = {}
for f in sorted(run.glob('*_seed*.jsonl')):
    arm, seed = f.stem.split('_seed')
    R = [json.loads(l) for l in open(f)]
    setup, end = R[0], R[-1]
    T = [r for r in R if 't' in r and 'type' not in r]
    appear = next((r['t'] for r in T if r['person'] is not None), None)
    take = [r for r in T if r['takeover'] and r['source'] == 'reflex']
    before = sum(1 for r in take if appear is None or r['t'] < appear)
    first = next((r['t'] for r in take if appear is not None and r['t'] >= appear), None)
    pm = [r['person_m'] for r in T if r['person_m'] is not None]
    arrived = end.get('result', '').startswith('arrived')
    rows[(arm, seed)] = dict(contacts=sum(r['contact'] for r in T), takeovers_before=before,
                             reaction_s=None if first is None else round(first - appear, 1),
                             arrived=arrived, result=end.get('result'), t_end=T[-1]['t'] if T else None,
                             min_person_m=round(min(pm), 2) if pm else None, min_wall_m=round(min(r['wall_m'] for r in T), 2),
                             reflex_count=T[-1]['reflex_count'] if T else 0)
    print(arm, seed, rows[(arm, seed)])
ref = [v for (a, _), v in rows.items() if a == 'reflex']
checks = dict(no_contacts=all(v['contacts'] == 0 for v in ref),
              no_early_takeover=all(v['takeovers_before'] == 0 for v in ref),
              reaction=sum(v['reaction_s'] is not None for v in ref) >= 2,
              arrived=sum(v['arrived'] for v in ref) >= 2)
print(checks, 'STAGE 6 SIM', 'PASSED' if all(checks.values()) and len(ref) == 3 else 'FAILED')
(run / 'STAGE6_RESULT.json').write_text(json.dumps(dict(checks=checks, rows={'%s_%s' % k: v for k, v in rows.items()}), indent=1))
