"""Prepare fixed public photos and exact, response-blind neuron selections."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sys
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / 'mapping_001'
for folder in ['config', 'inputs', 'vendor/fly_mapping']:
    (ROOT / folder).mkdir(parents=True, exist_ok=True)
for name in ['__init__.py', 'vision.py', 'commands.py']:
    shutil.copyfile(OLD / 'fly_mapping' / name, ROOT / 'vendor/fly_mapping' / name)
shutil.copyfile(OLD / 'config/neuron_registry.json', ROOT / 'config/readout_registry.json')
shutil.copyfile(OLD / 'config/mapping_profile.json', ROOT / 'config/mapping_profile.json')
sys.path.insert(0, str(ROOT / 'vendor'))
from fly_mapping.vision import VisualEncoder
registry = json.loads((ROOT / 'config/readout_registry.json').read_text())
profile = json.loads((ROOT / 'config/mapping_profile.json').read_text())
annotation_path = OLD / 'evidence/supplemental_files_Supplemental_file1_neuron_annotations.tsv'
comp = OLD / 'evidence/2025_Completeness_783.csv'
assert hashlib.sha256(annotation_path.read_bytes()).hexdigest() == registry['annotation_sha256']
assert hashlib.sha256(comp.read_bytes()).hexdigest() == registry['model_completeness_sha256']
with comp.open(newline='') as f:
    model_ids = [row[0] for row in list(csv.reader(f))[1:]]
assert len(model_ids) == len(set(model_ids)) == 138639
index = {v: i for i, v in enumerate(model_ids)}
with annotation_path.open(encoding='utf-8', newline='') as f:
    annotations = list(csv.DictReader(f, delimiter='\t'))
lc9, excluded = [], []
for row in annotations:
    if row['cell_type'] != 'LC9':
        continue
    if row['root_id'] not in index:
        excluded.append(row['root_id']); continue
    assert row['side'] in ['left', 'right']
    lc9.append({'root_id': row['root_id'], 'model_index': index[row['root_id']],
                'cell_type': 'LC9', 'side': row['side'], 'predicted_nt': row['top_nt']})
lc9.sort(key=lambda x: x['model_index'])
assert len(lc9) == 179
hs = [registry['cells'][k] for k in registry['visual_input_keys']]
assert not {x['root_id'] for x in lc9} & {registry['cells'][k]['root_id'] for k in registry['readout_keys']}
(ROOT / 'config/startup_registry.json').write_text(json.dumps({'candidate': 'LC9_TO_P9', 'lc9': lc9,
    'excluded_absent_from_model': excluded, 'input_count': len(lc9) + len(hs),
    'annotation_sha256': registry['annotation_sha256']}, indent=2) + '\n', encoding='utf-8')
# All-model annotations support descriptive tables, not output-cell selection.
labels = {row['root_id']: {'cell_type': row['cell_type'], 'side': row['side'], 'flow': row['flow']} for row in annotations}
(ROOT / 'config/model_labels.json').write_text(json.dumps([dict(root_id=rid, **labels.get(rid, {})) for rid in model_ids]) + '\n', encoding='utf-8')


def shifted(image, dx):
    positions = np.clip(np.arange(image.shape[1]) - dx, 0, image.shape[1]-1)
    return image[:, positions].copy()


def condition(name, hs_rates, lc9_rates, metadata):
    rates = np.zeros(138639, dtype=np.float32)
    for rid, value in hs_rates.items(): rates[index[rid]] = value
    for cell in lc9: rates[cell['model_index']] = lc9_rates[cell['side']]
    assert np.isfinite(rates).all() and 0 <= rates.min() <= rates.max() <= 200
    np.save(ROOT / 'inputs' / (name + '_rates.npy'), rates, allow_pickle=False)
    return dict(name=name, rates_file='inputs/' + name + '_rates.npy', metadata=metadata)


conditions = [condition('ZERO', {}, {'left':0, 'right':0}, {'kind':'zero'})]
for side in ['LEFT', 'RIGHT']:
    rates = {cell['root_id']: 200 if cell['anatomical_side'] == side.lower() else 5 for cell in hs}
    conditions.append(condition('HS_'+side, rates, {'left':0, 'right':0}, {'kind':'HS_control'}))
for value in [50,100,200]:
    conditions.append(condition('LC9_'+str(value), {}, {'left':value, 'right':value}, {'kind':'LC9_dose_control'}))
for photo in ['china', 'flower', 'blank']:
    image = np.full((120,160,3), 128, dtype=np.uint8) if photo == 'blank' else np.asarray(ImageOps.fit(Image.open(ROOT/'photos'/(photo+'.jpg')).convert('RGB'), (160,120), method=Image.Resampling.LANCZOS))
    Image.fromarray(image).save(ROOT/'inputs'/(photo+'_resized.png'))
    grey = image.astype(np.float32) / 255 @ np.array([0.299,0.587,0.114],dtype=np.float32)
    contrast = {side:float(grey[:,i*80:(i+1)*80].std()) for i,side in enumerate(['left','right'])}
    startup = {side:float(200*np.clip(value/0.25,0,1)) for side,value in contrast.items()}
    for direction,dx in ([('STATIC',0)] if photo == 'blank' else [('STATIC',0),('LEFT',-4),('RIGHT',4)]):
        encoder = VisualEncoder(registry,profile,'photo','OFFLINE_PHOTO_CLOCK')
        encoder.consume(image, session_id='photo',sequence=1,source_ns=1_000_000_000,now_ns=1_000_000_000,clock_id='OFFLINE_PHOTO_CLOCK')
        encoded = encoder.consume(shifted(image,dx), session_id='photo',sequence=2,source_ns=1_100_000_000,now_ns=1_100_000_000,clock_id='OFFLINE_PHOTO_CLOCK')
        for branch in (['COMBINED'] if photo == 'blank' else ['HS_ONLY','LC9_ONLY','COMBINED']):
            name = photo+'_'+direction+'_'+branch
            conditions.append(condition(name, encoded['rates_hz'] if branch!='LC9_ONLY' else {}, startup if branch!='HS_ONLY' else {'left':0,'right':0},
                {'kind':'photo_proxy','photo':photo,'direction':direction,'branch':branch,
                 'hs_valid':encoded['valid'],'hs_reason':encoded['reason'],'hs_features':encoded.get('features',{}),
                 'static_contrast':contrast,'lc9_rates_hz':startup,'artificial_shift_px':dx,
                 'source_is_video':False,'motion_publish_allowed':False}))
assert len(conditions)==25
(ROOT / 'config/conditions.json').write_text(json.dumps(conditions,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':'PASS','lc9_cells':len(lc9),'total_inputs':185,'conditions':25,'seeds':[20260923,20260924,20260925]}))
