"""One bounded EEG job. Never imports robot interfaces. JSON lines to parent only."""
import os,sys,json,pathlib,subprocess,contextlib,time
os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
ROOT=pathlib.Path(__file__).resolve().parents[1]
req=json.loads(sys.argv[1])
def emit(x):print(json.dumps(x),flush=True)
emit(dict(type='phase',phase='TCFormer 正在读取真实 EEG 并重新推理'))
r=subprocess.run(['<SERVER_HOME>/projects/tcformer-venv/bin/python',str(ROOT/'live-console/infer.py'),json.dumps(req)],capture_output=True,text=True,timeout=120)
if r.returncode:raise RuntimeError('TCFormer failed: '+r.stderr[-1800:])
inference=json.loads(r.stdout)
emit(dict(type='inference',data=inference))
sys.path.insert(0,str(ROOT/'source/inference_service/mappings/loom_005'))
sys.path.insert(0,str(ROOT/'experiments/eeg_dna02'))
with contextlib.redirect_stdout(sys.stderr):
 import numpy as np,torch
 from brain import Brain
 from decoder import DecoderV4
 from eeg_stimulus import Encoder,layout
 torch.set_num_threads(4);torch.cuda.set_per_process_memory_fraction(.45)
 p=ROOT/'source/inference_service/mappings/loom_005'
 reg=json.loads((p/'config/loom_registry.json').read_text());indices,old,cells=layout(reg)
 (p/'cache').mkdir(exist_ok=True)
 brain=Brain(reg,indices,p/'cache',zero_refractory_indices=old)
 dec=DecoderV4();enc=Encoder(gain_hz=20)
emit(dict(type='phase',phase='果蝇模型已加载；DNa02 保留 2.2ms 不应期；V4 原解码器'))
window=0
for seq,row in enumerate(inference['rows']):
 # Fresh replay exposure of a historical EEG trial, not a live acquisition timestamp.
 rates,reason=enc.encode(row['probabilities'],seq,float(seq),float(seq))
 emit(dict(type='trial',data=row,gate=reason,stimulus=rates))
 for j in range(40):
  started=time.monotonic()
  v=np.zeros(len(indices),dtype=np.float32)
  if j<10:v[-2:]=[rates['left'],rates['right']]
  with contextlib.redirect_stdout(sys.stderr):delta,total,ms=brain.step(v)
  hz={k:x/brain.window_s for k,x in brain.readouts_by_type(delta).items()}
  intent=dec.decode(hz,window*.1)
  emit(dict(type='window',window=window,trial=row['trial'],phase='stimulus' if j<10 else 'withdrawal',
   gate=reason,stim_left=float(v[-2]),stim_right=float(v[-1]),dna_left=hz.get(('DNa02','left'),0),dna_right=hz.get(('DNa02','right'),0),
   intent=intent,brain_ms=ms,source='dataset_replay',generated_mono=time.monotonic()))
  window+=1
  time.sleep(max(0,.1-(time.monotonic()-started)))
emit(dict(type='done'))
