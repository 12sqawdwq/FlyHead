"""Bounded GPU calibration and saved-TCFormer probability replay; no robot I/O."""
import os
os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
import sys,json,time,hashlib,pathlib
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[2]
LOOM=ROOT/'source/inference_service/mappings/loom_005'
sys.path.insert(0,str(LOOM))
from eeg_stimulus import Encoder,layout
from brain import Brain
from decoder import DecoderV4
import torch

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
OUT=ROOT/'results'/os.environ.get('EEG_RUN_ID','eeg_dna02_001')
OUT.mkdir(parents=True,exist_ok=False)
reg=json.loads((LOOM/'config/loom_registry.json').read_text())
indices,original,cells=layout(reg)
torch.set_num_threads(4)
torch.cuda.set_per_process_memory_fraction(.45)
probs_path=pathlib.Path('<SERVER_HOME>/projects/tcformer-paper/reproduction/seed0_subject01/predictions.npz')
manifest=dict(mode='OFFLINE_NO_ROBOT_IO',decoder_version=4,decoder_sha256=sha(LOOM/'decoder.py'),
    registry_sha256=sha(LOOM/'config/loom_registry.json'),prediction_sha256=sha(probs_path),
    stimulation_cells=cells,seeds=[101,202,303],levels_hz=[0,10,20,40,80],
    calibration_on_windows=10,off_windows=5,window_s=.1,replay_gain_hz=40,replay_threshold=.8,
    replay_selection='first 20 test indices per ground-truth class, chronological sort; no outcome selection',
    refractory_policy='original LC inputs zero; added DNa02 retains upstream 2.2ms',
    source='saved_TCFormer_subject01_seed0_test_probabilities; not fresh live EEG',
    no_lidar=True,no_service=True,gpu=torch.cuda.get_device_name(0))
(OUT/'protocol.json').write_text(json.dumps(manifest,indent=2))
(LOOM/'cache').mkdir(exist_ok=True)
brain=Brain(reg,indices,LOOM/'cache',zero_refractory_indices=original)
# Assert the two added targets retain their original refractory duration.
actual=brain.engine.model.original.refrac_steps if hasattr(brain.engine.model.original,'refrac_steps') else None
# TorchModel wraps the conductance model; inspect its registered modules below.
refrac=[]
for module in brain.engine.model.original.modules():
    if hasattr(module,'refrac_steps'):
        refrac.append(module.refrac_steps[indices[-2:]].tolist())
assert refrac and all(x==[22,22] for x in refrac),refrac
manifest['added_target_refractory_steps']=refrac
(OUT/'protocol.json').write_text(json.dumps(manifest,indent=2))
log=(OUT/'windows.jsonl').open('w')
rows=[];started=time.monotonic()
def episode(tag,left,right,seed,extra=None):
    brain.engine.reset(brain.zero,seed)
    brain.prev_total=None;brain.prev_readout.fill(0)
    decoder=DecoderV4();on=[];off=[]
    for j in range(15):
        rates=np.zeros(len(indices),dtype=np.float32)
        if j<10:rates[-2:]=[left,right]
        delta,total,ms=brain.step(rates)
        hz={k:v/brain.window_s for k,v in brain.readouts_by_type(delta).items()}
        intent=decoder.decode(hz,j*.1)
        row=dict(tag=tag,seed=seed,window=j,on=j<10,stim_left=float(rates[-2]),stim_right=float(rates[-1]),
            dna_left=hz.get(('DNa02','left'),0),dna_right=hz.get(('DNa02','right'),0),intent=intent,brain_ms=ms,all_spikes=total)
        log.write(json.dumps(row)+'\n');log.flush()
        (on if j<10 else off).append(row)
        if time.monotonic()-started>600:raise RuntimeError('600s budget exceeded')
    result=dict(tag=tag,seed=seed,left_hz=left,right_hz=right,
        mean_w=float(np.mean([x['intent']['w'] for x in on])),mean_v=float(np.mean([x['intent']['v'] for x in on])),
        dna_left=float(np.mean([x['dna_left'] for x in on])),dna_right=float(np.mean([x['dna_right'] for x in on])),
        off_max_abs_w=max(abs(x['intent']['w']) for x in off),off_last_w=off[-1]['intent']['w'],
        states=sorted(set(x['intent']['state'] for x in on)),**(extra or {}))
    rows.append(result);print(json.dumps(result),flush=True)
for seed in [101,202,303]:
    episode('baseline',0.,0.,seed)
    for rate in [10.,20.,40.,80.]:
        episode('left',rate,0.,seed)
        episode('right',0.,rate,seed)
a=np.load(probs_path)
selected=sorted(np.concatenate([np.flatnonzero(a['y_true']==c)[:20] for c in [0,1]]).tolist())
encoder=Encoder()
for seq,idx in enumerate(selected):
    probs=a['probabilities'][idx].astype(float).tolist()
    rates,reason=encoder.encode(probs,seq,float(seq),float(seq))
    episode('eeg_replay',rates['left'],rates['right'],1000+seq,
        dict(trial_index=idx,truth=int(a['y_true'][idx]),prediction=int(np.argmax(probs)),probabilities=probs,gate=reason))
cal=[r for r in rows if r['tag'] in ('left','right')]
replay=[r for r in rows if r['tag']=='eeg_replay'];accepted=[r for r in replay if r['gate']=='accepted']
def signok(r,label):return r['mean_w']>0 if label==0 else r['mean_w']<0
summary=dict(calibration_cases=len(cal),calibration_direction_correct=sum(signok(r,0 if r['tag']=='left' else 1) for r in cal),
    replay_trials=len(replay),accepted=len(accepted),rejected=len(replay)-len(accepted),
    accepted_direction_matches_prediction=sum(signok(r,r['prediction']) for r in accepted),
    accepted_direction_matches_truth=sum(signok(r,r['truth']) for r in accepted),
    classifier_correct=sum(r['prediction']==r['truth'] for r in replay),
    gpu_peak_mib=torch.cuda.max_memory_allocated()/2**20,elapsed_s=time.monotonic()-started,
    max_off_last_abs_w=max(abs(r['off_last_w']) for r in rows),
    limitations=['DNa02 direct stimulation/readout, not proof of upstream brain computation',
    '40 selected trials, reset between trials, saved probability replay only',
    'no lidar combination, no network or live stop test, no robot commands'])
(OUT/'episodes.json').write_text(json.dumps(rows,indent=2))
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
print('SUMMARY',json.dumps(summary),flush=True)

