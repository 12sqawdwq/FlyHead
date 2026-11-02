"""Independent CPU validation of frozen probe counts and shadow arithmetic."""
from pathlib import Path
import hashlib
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
run = ROOT / 'runs/probe_001'
report = json.loads((run / 'RESULTS.json').read_text())
registry = json.loads((ROOT / 'config/neuron_registry.json').read_text())
profile = json.loads((ROOT / 'config/mapping_profile.json').read_text())
assert report['status'] == 'PASS_TECHNICAL_PROBE'
assert report['model_graph_cropped'] is False and report['motion_published'] is False
assert report['protocol_sha256'] == hashlib.sha256((ROOT / 'protocol_lock.json').read_bytes()).hexdigest()
assert set(report['conditions']) == {'ZERO', 'TONIC', 'LEFT_IMAGE_MOTION', 'RIGHT_IMAGE_MOTION'}
inputs = {registry['cells'][key]['root_id'] for key in registry['visual_input_keys']}
primary_keys = ['DNa02_left', 'DNa02_right', 'DNp09_left', 'DNp09_right']
rows = []
for name, condition in report['conditions'].items():
    path = run / condition['counts_file']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == condition['counts_sha256']
    counts = np.load(path, allow_pickle=False)
    assert counts.shape == (138639,) and np.issubdtype(counts.dtype, np.integer)
    assert counts.min() >= 0 and counts.max() <= 1000
    assert int(counts.sum()) == condition['total_spikes']
    assert int(np.count_nonzero(counts)) == condition['active_neurons']
    assert set(condition['drive']['rates_hz']) == inputs
    rates = {}
    for key in registry['readout_keys']:
        cell = registry['cells'][key]
        n = int(counts[cell['model_index']])
        assert n == condition['neural_counts_by_id'][cell['root_id']]
        rates[key] = n / 0.1
    intent = condition['offline_shadow_intent']
    expected_v = min((rates['DNp09_left'] + rates['DNp09_right']) / 2 / 100, 1) * 0.1
    expected_w = float(np.clip((rates['DNa02_left'] - rates['DNa02_right']) / 100, -1, 1)) * 0.3
    assert abs(intent['shadow_forward_m_s'] - expected_v) < 1e-12
    assert abs(intent['shadow_yaw_rad_s'] - expected_w) < 1e-12
    assert intent['publish_allowed'] is False and intent['ros_motion_command'] is None
    rows.append({'condition': name, 'primary_rates_hz': {key: rates[key] for key in primary_keys},
                 'all_readout_rates_hz': rates, 'shadow_state': intent['state'],
                 'shadow_forward_m_s': expected_v, 'shadow_yaw_rad_s': expected_w,
                 'wall_seconds': condition['wall_seconds'],
                 'model_only_realtime_ratio': condition['model_only_realtime_ratio']})
assert report['conditions']['ZERO']['total_spikes'] == 0
left = next(row for row in rows if row['condition'] == 'LEFT_IMAGE_MOTION')
right = next(row for row in rows if row['condition'] == 'RIGHT_IMAGE_MOTION')
result = {'status': 'PASS_ARTIFACT_AND_ARITHMETIC_VALIDATION',
          'physical_or_biological_validation': False, 'real_camera_used': False,
          'rows': rows,
          'primary_readout_nonzero': any(any(v > 0 for v in row['primary_rates_hz'].values()) for row in [left, right]),
          'left_right_primary_readouts_differ': left['primary_rates_hz'] != right['primary_rates_hz'],
          'forward_readout_nonzero': any(row['primary_rates_hz']['DNp09_left'] + row['primary_rates_hz']['DNp09_right'] > 0 for row in [left,right]),
          'turn_readout_nonzero': any(row['primary_rates_hz']['DNa02_left'] + row['primary_rates_hz']['DNa02_right'] > 0 for row in [left,right]),
          'live_motion_admitted': False}
(ROOT / 'evidence/INDEPENDENT_VALIDATION.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
