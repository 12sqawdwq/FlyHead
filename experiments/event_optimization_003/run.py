from pathlib import Path
import contextlib,hashlib,json,os,sys,time
ROOT=Path(__file__).resolve().parent
BASE=Path('<SERVER_ROOT>/inference_service/deployments/flywire_lif_001')
PHOTO=ROOT.parent/'photo_startup_002'
GIB=1024**3
os.environ['TRITON_CACHE_DIR']=str(ROOT/'triton_cache')
for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[k]='4'

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def dump(p,d):p.write_bytes((json.dumps(d,indent=2)+'\n').encode())
lock=json.loads((ROOT/'protocol_lock.json').read_text())
for row in lock['local_files']:assert sha(ROOT/row['path'])==row['sha256']
for row in lock['external_files']:assert sha(row['path'])==row['sha256']
import pyarrow
import numpy as np
import torch
import triton
sys.path[:0]=[str(PHOTO),str(BASE/'upstream/code')]
import run_pytorch as backend
from service.engines import EagerEngine,GraphEngine
from event_model import EventModel

torch.set_num_threads(4);torch.set_num_interop_threads(1)
RUN=ROOT/'run_001';RUN.mkdir()
r={'status':'RUNNING','scope':'FULL_GRAPH_EXACT_EVENT_PROPAGATION','protocol_sha256':sha(ROOT/'protocol_lock.json'),'robot_io':False,'equivalence':[]}
def guard(start=False):
 av=next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))
 rss=next(int(s.split()[1])*1024 for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('VmRSS:'))
 if av<(20 if start else 12)*GIB or rss>6*GIB:raise RuntimeError('HOST_GATE')
 return {'available':av,'rss':rss}
try:
 guard(True)
 free,total=torch.cuda.mem_get_info()
 if free<5*GIB:raise RuntimeError('GPU_FREE_GATE')
 torch.cuda.set_per_process_memory_fraction(1*GIB/total)
 import shutil,subprocess
 if shutil.disk_usage(ROOT).free<40*GIB:raise RuntimeError('DISK_GATE')
 r['gpu_telemetry_before']=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free,utilization.gpu','--format=csv,noheader'],text=True).strip()
 r['triton']=triton.__version__;r['timing_scope']='SHARED_GPU_DESCRIPTIVE_ONLY'
 reg=json.loads((PHOTO/'config/readout_registry.json').read_text());lc=json.loads((PHOTO/'config/startup_registry.json').read_text())
 inputs=[reg['cells'][k]['model_index'] for k in reg['visual_input_keys']]+[c['model_index'] for c in lc['lc9']]
 assert len(inputs)==185
 (ROOT/'cache').mkdir()
 setup=time.perf_counter()
 with contextlib.redirect_stdout(sys.stderr):
  cpu=backend.get_weights(str(BASE/'upstream/data/2025_Connectivity_783.parquet'),str(BASE/'upstream/data/2025_Completeness_783.csv'),str(ROOT/'cache'),csr=True)
 values=cpu.values().numpy();ptr=cpu.crow_indices().numpy()
 assert np.isfinite(values).all() and np.array_equal(values,np.round(values))
 sums=np.add.reduceat(np.abs(values.astype(np.int64)),ptr[:-1][np.diff(ptr)>0])
 assert sums.max()<2**24 and cpu._nnz()==15091983
 r['integer_exactness_guard']={'max_absolute_postsynaptic_weight_sum':int(sums.max()),'upper_bound':2**24-1,'all_weights_integral':True}
 original=backend.TorchModel(1,138639,backend.DT,backend.MODEL_PARAMS,cpu.to('cuda'),exc_indices=inputs,device='cuda').eval()
 outgoing=cpu.transpose(0,1).to_sparse_csr()
 assert outgoing._nnz()==15091983
 event=EventModel(original,outgoing).eval()
 del cpu,outgoing,values,ptr,sums
 eager=EagerEngine(original,138639)
 rates={name:torch.tensor(np.load(PHOTO/'inputs'/(name+'_rates.npy'),allow_pickle=False),device='cuda') for name in ['ZERO','HS_LEFT','HS_RIGHT','LC9_200','china_STATIC_COMBINED','flower_STATIC_COMBINED']}
 def advance(engine,blocks):
  for j in range(blocks):
   engine.block()
   if (j+1)%10==0:
    guard()
    if not engine.healthy():raise RuntimeError('NONFINITE_STATE')
  torch.cuda.synchronize()
 with torch.no_grad():
  t=time.perf_counter();fast=GraphEngine(event,138639);r['jit_and_capture_seconds']=time.perf_counter()-t
  r['setup_seconds']=time.perf_counter()-setup
  for name,rate in rates.items():
   data={}
   for tag,engine in [('reference',eager),('event',fast)]:
    engine.reset(rate,20260923);advance(engine,50)
    data[tag]={'counts':engine.counts.cpu().numpy().copy(),**{'state_'+str(i):t.cpu().numpy().copy() for i,t in enumerate(engine.state)}}
    np.savez_compressed(RUN/(name+'_'+tag+'.npz'),**data[tag])
   errors=[float(np.max(np.abs(data['reference']['state_'+str(i)]-data['event']['state_'+str(i)]))) for i in range(5)]
   exact=np.array_equal(data['reference']['counts'],data['event']['counts'])
   row={'condition':name,'counts_exact':exact,'state_errors':errors,'pass':exact and max(errors)<=1e-5}
   r['equivalence'].append(row);dump(RUN/'STATUS.json',r);print(json.dumps(row),flush=True)
  r['accepted']=all(x['pass'] for x in r['equivalence'])
  if r['accepted']:
   r['timings']={}
   for name in ['HS_LEFT','LC9_200']:
    samples={'reference':[],'event':[]}
    # Alternate backends to reduce order confounding under shared load.
    for rep in range(11):
     for tag,engine in [('reference',eager),('event',fast)]:
      engine.reset(rates[name],20260923)
      t=time.perf_counter();advance(engine,10);elapsed=time.perf_counter()-t
      if rep:samples[tag].append(elapsed)
    r['timings'][name]={'seconds':samples,'reference_median_ms':float(np.median(samples['reference'])*1000),'event_median_ms':float(np.median(samples['event'])*1000),'median_speedup':float(np.median(samples['reference'])/np.median(samples['event']))}
  r['peak_allocated_bytes']=torch.cuda.max_memory_allocated();r['peak_reserved_bytes']=torch.cuda.max_memory_reserved()
  r['resources_end']=guard();r['status']='COMPLETE_TECHNICAL_VALIDATION'
  dump(RUN/'RESULTS.json',r);dump(RUN/'STATUS.json',r)
except Exception as e:
 r.update(status='FAIL',error=repr(e));dump(RUN/'RESULTS.json',r);raise
