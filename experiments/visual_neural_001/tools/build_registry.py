"""Compile exact FlyWire783 cell identities; never infer receptive fields from anatomy."""
from pathlib import Path
import csv
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence'
ANNOTATION = EVIDENCE / 'supplemental_files_Supplemental_file1_neuron_annotations.tsv'
COMPLETENESS = EVIDENCE / '2025_Completeness_783.csv'
TYPES = ['HSN', 'HSE', 'HSS', 'DNa02', 'DNp09', 'DNa01', 'DNp01']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with COMPLETENESS.open(newline='', encoding='utf-8') as stream:
    rows = list(csv.reader(stream))
ids = [row[0] for row in rows[1:]]
assert len(ids) == len(set(ids)) == 138639
indices = {root_id: index for index, root_id in enumerate(ids)}
cells = {}
conflicts = []
with ANNOTATION.open(newline='', encoding='utf-8') as stream:
    for row in csv.DictReader(stream, delimiter='\t'):
        if row['hemibrain_type'] in TYPES and row['cell_type'] != row['hemibrain_type']:
            conflicts.append({key: row[key] for key in ['root_id', 'cell_type', 'hemibrain_type', 'side']})
        if row['cell_type'] not in TYPES:
            continue
        key = row['cell_type'] + '_' + row['side']
        if row['side'] not in ('left', 'right') or key in cells:
            raise RuntimeError('AMBIGUOUS_EXACT_CELL_TYPE:' + key)
        if row['root_id'] not in indices:
            raise RuntimeError('CELL_NOT_IN_DEPLOYED_MODEL:' + row['root_id'])
        cells[key] = {'root_id': row['root_id'], 'model_index': indices[row['root_id']],
                      'cell_type': row['cell_type'], 'anatomical_side': row['side'],
                      'flow': row['flow'], 'predicted_nt': row['top_nt'],
                      'hemibrain_type_reference_only': row['hemibrain_type']}
assert set(cells) == {kind + '_' + side for kind in TYPES for side in ['left', 'right']}
inputs = [kind + '_' + side for kind in ['HSN', 'HSE', 'HSS'] for side in ['left', 'right']]
outputs = [kind + '_' + side for kind in ['DNa02', 'DNp09', 'DNa01', 'DNp01'] for side in ['left', 'right']]
assert not ({cells[k]['root_id'] for k in inputs} & {cells[k]['root_id'] for k in outputs})
registry = {'schema_version': 1, 'dataset': 'FlyWire783', 'model_neurons': len(ids),
            'annotation_commit': '8587524c1748ce5ef2080822a2fc890fc03bf597',
            'annotation_sha256': digest(ANNOTATION), 'model_completeness_sha256': digest(COMPLETENESS),
            'identity_rule': 'exact current cell_type then exact root_id join; no synonym union',
            'encoding_mode': 'ENGINEERED_HS_VISUAL_MOTION_PROXY_NOT_RETINAL_RECONSTRUCTION',
            'anatomical_side_is_validated_camera_field': False,
            'robot_yaw_sign_calibrated': False,
            'cells': cells, 'visual_input_keys': inputs, 'readout_keys': outputs,
            'excluded_cross_namespace_name_collisions': conflicts,
            'upstream_p9_comment_conflict': {
                '720575940627652358': 'upstream comment left; current annotation right',
                '720575940635872101': 'upstream comment right; current annotation left'},
            'oDN1': 'not resolved by exact annotation; not silently equated to P9'}
(ROOT / 'config').mkdir(exist_ok=True)
(ROOT / 'config/neuron_registry.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'status': 'PASS', 'visual_inputs': len(inputs), 'readouts': len(outputs),
                  'excluded_collisions': len(conflicts)}, indent=2))
