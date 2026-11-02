"""Build config/loom_registry.json: exact cell_type -> root_id -> model_index, annotation SHA locked.

Run on the 5090D with the flywire_lif_001 environment:
  env/bin/python tools/build_registry.py ANNOTATIONS.tsv COMPLETENESS.csv OUT.json
"""
import hashlib
import json
import sys

import pandas as pd

ANNOTATION_SHA256 = '9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be'
COMPLETENESS_SHA256 = '52b0ac6094cd32c546f8d4c341e094376f48f4e791f8db9b166de5dff8199ea4'
INPUT_TYPES = ['LC4', 'LPLC2', 'LC9']
READOUT_TYPES = ['DNp01', 'DNp02', 'DNp04', 'DNp06', 'DNp11', 'DNp09', 'DNa01', 'DNa02', 'MDN']


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 23), b''):
            h.update(block)
    return h.hexdigest()


def main(ann_path, comp_path, out_path):
    assert sha(ann_path) == ANNOTATION_SHA256, 'annotation file differs from the locked one'
    assert sha(comp_path) == COMPLETENESS_SHA256, 'completeness file differs from the locked one'
    ann = pd.read_csv(ann_path, sep='\t', dtype={'root_id': str}, low_memory=False)
    comp = pd.read_csv(comp_path, dtype={0: str})
    index = {r: i for i, r in enumerate(comp.iloc[:, 0].astype(str))}
    assert len(index) == 138639 and index['720575940604737708'] == 904

    def cells(cell_type):
        rows = ann[ann.cell_type == cell_type]          # exact current cell_type, no synonyms
        out = []
        for r in rows.itertuples():
            assert r.root_id in index, (cell_type, r.root_id)
            out.append(dict(root_id=r.root_id, model_index=index[r.root_id], cell_type=cell_type,
                            anatomical_side=r.side))
        return sorted(out, key=lambda c: c['model_index'])

    registry = dict(
        schema_version=1, dataset='FlyWire783', model_neurons=138639,
        annotation_sha256=ANNOTATION_SHA256, model_completeness_sha256=COMPLETENESS_SHA256,
        identity_rule='exact current cell_type then exact root_id join; no synonym union',
        encoding_mode='ENGINEERED_LIDAR_LOOM_PROXY_NOT_RETINAL_RECONSTRUCTION',
        field_to_eye_assignment_validated=False, robot_yaw_sign_calibrated=False,
        inputs={t: cells(t) for t in INPUT_TYPES},
        readouts={t: cells(t) for t in READOUT_TYPES})
    all_in = [c['model_index'] for t in INPUT_TYPES for c in registry['inputs'][t]]
    all_out = [c['model_index'] for t in READOUT_TYPES for c in registry['readouts'][t]]
    assert len(set(all_in)) == len(all_in) and not set(all_in) & set(all_out)
    registry['counts'] = {t: len(v) for t, v in {**registry['inputs'], **registry['readouts']}.items()}
    with open(out_path, 'w') as f:
        json.dump(registry, f, indent=1)
    print(json.dumps(registry['counts']))


if __name__ == '__main__':
    main(*sys.argv[1:4])
