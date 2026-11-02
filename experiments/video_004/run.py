"""Stateful, media-clock video stimulation. Offline only; single execution slot."""
from pathlib import Path
import contextlib,hashlib,json,os,sys,time,shutil,subprocess
ROOT=Path(__file__).resolve().parent
BASE=Path('<SERVER_ROOT>/inference_service/deployments/flywire_lif_001')
GIB=1024**3
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4])
for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[k]='4'
os.environ['TRITON_CACHE_DIR']=str(ROOT/'triton_cache')
os.environ['CUDA_CACHE_PATH']=str(ROOT/'cuda_cache')
sys.path[:0]=[str(ROOT/'vendor'),str(ROOT),str(BASE/'upstream/code')]

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def dump(p,d):p.write_bytes((json.dumps(d,indent=2)+'\n').encode())
def guard(start=False):
 av=next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))
 rss=next(int(s.split()[1])*1024 for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('VmRSS:'))
 if av<(20 if start else 12)*GIB or rss>6*GIB:raise RuntimeError('HOST_RESOURCE_GATE')
 return {'available_bytes':av,'rss_bytes':rss}
lock=json.loads((ROOT/'protocol_lock.json').read_text())
for x in lock['local_files']:assert sha(ROOT/x['path'])==x['sha256'],x['path']
for x in lock['external_files']:assert sha(x['path'])==x['sha256'],x['path']
import pyarrow
pyarrow.set_cpu_count(4);pyarrow.set_io_thread_count(4)
import numpy as np
import torch
import run_pytorch as backend
from engines import EagerEngine,GraphEngine
from event_model import EventModel
from stream_input import StreamInput
from fly_mapping.commands import IntentDecoder

torch.set_num_threads(4);torch.set_num_interop_threads(1)
RUN=ROOT/'run_001';RUN.mkdir()
r={'status':'RUNNING','protocol_sha256':sha(ROOT/'protocol_lock.json'),'robot_io':False,'time_basis':'OFFLINE_MEDIA_PTS_NOT_SENSOR_CLOCK','neural_state_persistence':True,'equivalence':[],'episodes':[]}
dump(RUN/'STATUS.json',r)
try:
 r['resources_start']=guard(True)
 free,total=torch.cuda.mem_get_info()
 r['cuda_free_at_admission']=free
 if free<4.5*GIB:raise RuntimeError('GPU_START_GATE')
 torch.cuda.set_per_process_memory_fraction(.5*GIB/total)
 if shutil.disk_usage(ROOT).free<40*GIB:raise RuntimeError('DISK_GATE')
 r['gpu_telemetry_before']=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free,utilization.gpu','--format=csv,noheader'],text=True).strip()
 reg=json.loads((ROOT/'config/readout_registry.json').read_text());startup=json.loads((ROOT/'config/startup_registry.json').read_text());profile=json.loads((ROOT/'config/mapping_profile.json').read_text());videos=json.loads((ROOT/'config/videos.json').read_text())
 inputs=[reg['cells'][k]['model_index'] for k in reg['visual_input_keys']]+[c['model_index'] for c in startup['lc9']]
 readouts=[reg['cells'][k]['model_index'] for k in reg['readout_keys']]
 assert len(set(inputs))==185 and not set(inputs)&set(readouts)
 frames={v['name']:np.load(ROOT/v['frames_file'],allow_pickle=False) for v in videos}
 (ROOT/'cache').mkdir();setup=time.perf_counter()
 with contextlib.redirect_stdout(sys.stderr):
  cpu=backend.get_weights(str(BASE/'upstream/data/2025_Connectivity_783.parquet'),str(BASE/'upstream/data/2025_Completeness_783.csv'),str(ROOT/'cache'),csr=True)
 assert cpu._nnz()==15091983 and tuple(cpu.shape)==(138639,138639)
 values=cpu.values().numpy();ptr=cpu.crow_indices().numpy()
 assert np.isfinite(values).all() and np.array_equal(values,np.round(values))
 maximum=int(np.add.reduceat(np.abs(values.astype(np.int64)),ptr[:-1][np.diff(ptr)>0]).max());assert maximum<2**24
 r['model']={'neurons':138639,'connections':15091983,'dt_ms':backend.DT,'max_abs_weight_sum':maximum,'parameters':backend.MODEL_PARAMS}
 # EventModel uses original.neurons and original.poisson, not original.forward.
 # Keep its unused CSR on CPU; full outgoing connectivity remains on GPU.
 original=backend.TorchModel(1,138639,backend.DT,backend.MODEL_PARAMS,cpu,exc_indices=inputs,device='cuda').eval()
 outgoing=cpu.transpose(0,1).to_sparse_csr();assert outgoing._nnz()==15091983
 event=EventModel(original,outgoing).eval()
 reference=backend.TorchModel(1,138639,backend.DT,backend.MODEL_PARAMS,cpu.to('cuda'),exc_indices=inputs,device='cuda').eval()
 eager=EagerEngine(reference,138639)
 del outgoing,values,ptr
 input_gpu=torch.tensor(inputs,device='cuda');readout_gpu=torch.tensor(readouts,device='cuda')
 zero=torch.zeros(138639,dtype=torch.float32,device='cuda')
 def set_rates(engine,compact):engine.rates[0,input_gpu]=torch.as_tensor(compact,device='cuda')
 def reset_state_only(engine):
  # Counter and RNG deliberately persist: this intervention changes state only.
  for target,fresh in zip(engine.state,engine.model.state_init()):target.copy_(fresh)
 def advance(engine,record_bins=False):
  bins=[]
  for _ in range(10):
   engine.block()
   if record_bins:bins.append(engine.counts[readout_gpu].clone())
  torch.cuda.synchronize()
  if not engine.healthy():raise RuntimeError('NONFINITE_STATE')
  guard()
  return torch.stack(bins).cpu().numpy() if record_bins else None
 with torch.no_grad():
  fast=GraphEngine(event,138639)
  for video in videos:
   name=video['name'];eq={}
   for tag,engine in [('reference',eager),('event',fast)]:
    engine.reset(zero,20260923);enc=StreamInput(reg,startup,profile,'equivalence');counts=[]
    for k in range(5):
     rates,_=enc.encode(frames[name][k],k,'CONTINUOUS');set_rates(engine,rates);advance(engine)
     counts.append(engine.counts.cpu().numpy().copy())
    eq[tag]={'counts':np.stack(counts),**{'state_'+str(i):t.cpu().numpy().copy() for i,t in enumerate(engine.state)}}
    np.savez_compressed(RUN/('equivalence_'+name+'_'+tag+'.npz'),**eq[tag])
   exact=np.array_equal(eq['reference']['counts'],eq['event']['counts'])
   errors=[float(np.max(np.abs(eq['reference']['state_'+str(i)]-eq['event']['state_'+str(i)]))) for i in range(5)]
   r['equivalence'].append({'video':name,'frame_counts_exact':exact,'state_errors':errors,'pass':exact and max(errors)<=1e-5})
  dump(RUN/'EQUIVALENCE.json',r['equivalence'])
  if not all(x['pass'] for x in r['equivalence']):raise RuntimeError('DYNAMIC_EQUIVALENCE_GATE')
  del eager,reference,eq,cpu
  torch.cuda.empty_cache()
  r['setup_seconds']=time.perf_counter()-setup
  for video in videos:
   name=video['name'];timestamps=json.loads((ROOT/video['timestamps_file']).read_text())
   for arm in ['CONTINUOUS','FROZEN_FIRST','RESET_STATE','HS_ONLY']:
    for seed in [20260923,20260924]:
     eid=name+'__'+arm+'__'+str(seed);fast.reset(zero,seed)
     enc=StreamInput(reg,startup,profile,eid)
     decoder=IntentDecoder(reg,profile,session_id=eid,clock_id='OFFLINE_MEDIA_REPLAY',model_identity=r['protocol_sha256'])
     counts=np.empty((90,138639),dtype=np.uint16);rates_saved=np.empty((90,185),dtype=np.float32);bins=np.empty((900,8),dtype=np.int32)
     previous=np.zeros(138639,dtype=np.int32);previous_read=np.zeros(8,dtype=np.int32);rows=[]
     for k in range(90):
      total_start=time.perf_counter()
      image=None if k>=80 else frames[name][0 if arm=='FROZEN_FIRST' else k]
      encoding_start=time.perf_counter();rates,features=enc.encode(image,k,arm);encoding_ms=(time.perf_counter()-encoding_start)*1000
      rates_saved[k]=rates
      if arm=='RESET_STATE' and k>0:reset_state_only(fast)
      set_rates(fast,rates);torch.cuda.synchronize()
      model_start=time.perf_counter();cumulative_bins=advance(fast,True);model_ms=(time.perf_counter()-model_start)*1000
      transfer_start=time.perf_counter();current=fast.counts.cpu().numpy().copy();delta=current-previous
      assert delta.min()>=0 and delta.max()<=1000
      counts[k]=delta;previous=current
      bins[k*10:(k+1)*10]=np.diff(cumulative_bins,axis=0,prepend=previous_read[None,:]);previous_read=cumulative_bins[-1].copy()
      read={reg['cells'][key]['root_id']:int(delta[reg['cells'][key]['model_index']]) for key in reg['readout_keys']}
      tick=1_000_000_000+k*100_000_000
      intent=decoder.decode(read,window_s=.1,session_id=eid,sequence=k,source_ns=tick,now_ns=tick,clock_id='OFFLINE_MEDIA_REPLAY',model_identity=r['protocol_sha256'],brain_healthy=True,input_valid=features['hs_valid'] and features['frame_present'])
      transfer_ms=(time.perf_counter()-transfer_start)*1000
      # State summaries are stored this time, not merely checked for finiteness.
      summary={str(i):{'min':float(t.min().item()),'max':float(t.max().item())} for i,t in enumerate(fast.state)}
      total_ms=(time.perf_counter()-total_start)*1000
      source=None if k>=80 else timestamps[0 if arm=='FROZEN_FIRST' else k]
      rows.append({'frame':k,'replay_seconds':k/10,'neural_window_start_ms':k*100,'neural_window_end_ms':(k+1)*100,
       'original_video_source':source,'stimulus':features,'all_spikes':int(delta.sum()),'active_neurons':int(np.count_nonzero(delta)),
       'readout_counts':{key:int(delta[reg['cells'][key]['model_index']]) for key in reg['readout_keys']},'intent':intent,
       'encoding_ms':encoding_ms,'model_and_health_ms':model_ms,'transfer_decode_ms':transfer_ms,'processing_ms':total_ms,
       'within_100ms_compute_budget':total_ms<=100,'state_summary':summary,'live_admission':False})
     artifact=RUN/(eid+'.npz')
     np.savez_compressed(artifact,counts=counts,input_rates=rates_saved,readout_bins=bins,**{'final_state_'+str(i):t.cpu().numpy() for i,t in enumerate(fast.state)})
     output={'episode_id':eid,'video':name,'arm':arm,'seed':seed,'state_resets':90 if arm=='RESET_STATE' else 1,'rng_seed_resets':1,'frames':rows,'artifact':artifact.name,'artifact_sha256':sha(artifact)}
     dump(RUN/(eid+'.json'),output)
     r['episodes'].append({k:v for k,v in output.items() if k!='frames'})
     r['result_bytes']=sum(p.stat().st_size for p in RUN.iterdir() if p.is_file())
     if r['result_bytes']>512*1024**2:raise RuntimeError('OUTPUT_BUDGET')
     dump(RUN/'STATUS.json',r)
     print(json.dumps({'episode':eid,'frames':90,'spikes':int(counts.sum()),'model_median_ms':float(np.median([x['model_and_health_ms'] for x in rows]))}),flush=True)
  assert len(r['episodes'])==16
  r['resources_end']=guard();r['peak_allocated_bytes']=torch.cuda.max_memory_allocated();r['peak_reserved_bytes']=torch.cuda.max_memory_reserved()
  r['status']='COMPLETE_STATEFUL_VIDEO_PROBE';dump(RUN/'RESULTS.json',r);dump(RUN/'STATUS.json',r)
except Exception as e:
 r.update(status='FAIL',error=repr(e));dump(RUN/'RESULTS.json',r);dump(RUN/'STATUS.json',r);raise
