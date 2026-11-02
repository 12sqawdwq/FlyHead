"""Sweep v3 thresholds offline on stored pooled world ranges (features_v3.world_ranges_m)."""
import json, math, sys
import numpy as np
import retina as RT
S = [json.loads(l) for l in open(sys.argv[1])]
def run(deadband, closing):
    RT.RETINA_V2['deadband_rad_s'] = deadband
    ret = RT.LidarRetinaV3()
    orig = ret.step_world
    out = []
    for s in S:
        # closing-speed gate: patch approach_eps per scan from the baseline (closing m/s * dt)
        RT.RETINA_V2['approach_eps_m'] = closing * 0.12
        r, f = ret.step_world(s['features_v3']['world_ranges_m'], s['pose'][2], s['t'])
        out.append(max(f['left']['loom_rad_s'], f['right']['loom_rad_s']))
    return out
cls = []
for i in range(1, len(S)):
    s, a = S[i], S[i - 1]; dt = s['t'] - a['t']
    sp = math.hypot(s['pose'][0] - a['pose'][0], s['pose'][1] - a['pose'][1]) / dt if dt > 0 else 0
    yr = abs(math.remainder(s['pose'][2] - a['pose'][2], 2 * math.pi)) / dt if dt > 0 else 0
    near = min(s['features_v3']['left']['nearest_m'], s['features_v3']['right']['nearest_m'])
    cls.append('still' if sp < 0.03 and yr < 0.05 else 'turn' if sp < 0.05 and yr > 0.1 else 'near' if sp > 0.1 and near < 0.6 else 'drive' if sp > 0.1 else 'other')
print('%-22s %8s %8s %8s %8s   (share of scans with loom > 0.15 rad/s)' % ('deadband / closing', 'still', 'turn', 'drive', 'near<0.6'))
for db in (0.05, 0.08, 0.12):
    for cl in (0.0, 0.08, 0.15):
        L = run(db, cl)[1:]
        frac = lambda c: 100 * np.mean([l > 0.15 for l, k in zip(L, cls) if k == c] or [0])
        print('%-22s %7.1f%% %7.1f%% %7.1f%% %7.1f%%' % ('%.2f / %.2f m/s' % (db, cl), frac('still'), frac('turn'), frac('drive'), frac('near')))
