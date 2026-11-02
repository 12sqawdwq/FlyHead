"""One bounded locked run: equivalence, timing, and 75 offline photo/control trials."""
from pathlib import Path
import contextlib
import hashlib
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('<SERVER_ROOT>/inference_service/deployments/flywire_lif_001')
sys.path[:0] = [str(ROOT), str(ROOT/'vendor')]
GIB = 1024**3


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8*1024*1024), b''): h.update(block)
    return h.hexdigest()


def dump(path, data):
    path.write_bytes((json.dumps(data, indent=2, ensure_ascii=False)+'\n').encode('utf-8'))


def guard(start=False):
    available = next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))
    rss = next(int(s.split()[1])*1024 for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('VmRSS:'))
    if available < (20 if start else 12)*GIB or rss > 6*GIB:
        raise RuntimeError('HOST_RESOURCE_GATE')
    return {'available_bytes':available,'rss_bytes':rss}


lock = json.loads((ROOT/'protocol_lock_shared.json').read_text())
for row in lock['local_files']: assert sha(ROOT/row['path']) == row['sha256'], row['path']
for row in lock['external_files']: assert sha(row['path']) == row['sha256'], row['path']
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']: os.environ[key]='4'
import pyarrow
import numpy as np
import pandas as pd
import torch
from service.engines import EagerEngine, GraphEngine
from fly_mapping.commands import IntentDecoder
sys.path.insert(0, str(BASE/'upstream/code'))
import run_pytorch as backend

torch.set_num_threads(4)
torch.set_num_interop_threads(1)
RUN = ROOT/'run_002'
RUN.mkdir()  # occupied run slots are never reused
report = {'status':'RUNNING','protocol_sha256':sha(ROOT/'protocol_lock_shared.json'),
          'resource_mode':'SHARED_GPU_CONTENDED_NOT_EXCLUSIVE_BENCHMARK',
          'robot_io':False,'real_video':False,'graph_cropped':False,'trials':[]}
dump(RUN/'STATUS.json',report)
try:
    report['resources_start']=guard(start=True)
    import shutil
    if shutil.disk_usage(ROOT).free < 40*GIB: raise RuntimeError('DISK_GATE')
    free,total=torch.cuda.mem_get_info()
    report['cuda_free_bytes_at_admission']=free
    import subprocess
    report['gpu_telemetry_before']=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free,utilization.gpu','--format=csv,noheader'],text=True).strip()
    if free < 5.25*GIB: raise RuntimeError('GPU_FREE_GATE')
    torch.cuda.set_per_process_memory_fraction(1.25*GIB/total)
    torch.cuda.reset_peak_memory_stats()
    registry=json.loads((ROOT/'config/readout_registry.json').read_text())
    startup=json.loads((ROOT/'config/startup_registry.json').read_text())
    profile=json.loads((ROOT/'config/mapping_profile.json').read_text())
    conditions=json.loads((ROOT/'config/conditions.json').read_text())
    labels=json.loads((ROOT/'config/model_labels.json').read_text())
    ids,index_to_id=backend.get_hash_tables(str(BASE/'upstream/data/2025_Completeness_783.csv'))
    n=len(ids);assert n==138639
    inputs=[registry['cells'][k]['model_index'] for k in registry['visual_input_keys']]+[c['model_index'] for c in startup['lc9']]
    readouts=[registry['cells'][k]['model_index'] for k in registry['readout_keys']]
    lc9_indices=[c['model_index'] for c in startup['lc9']]
    assert len(set(inputs))==185 and not set(inputs)&set(readouts)
    for c in startup['lc9']:assert ids[int(c['root_id'])]==c['model_index']
    cache=ROOT/'cache_shared';cache.mkdir()
    setup=time.perf_counter()
    with contextlib.redirect_stdout(sys.stderr):
        cpu_weights=backend.get_weights(str(BASE/'upstream/data/2025_Connectivity_783.parquet'),str(BASE/'upstream/data/2025_Completeness_783.csv'),str(cache),csr=True)
    assert cpu_weights._nnz()==15091983 and torch.isfinite(cpu_weights.values()).all()
    # Structural audit, not response-driven input selection.
    pointer=cpu_weights.crow_indices().numpy();columns=cpu_weights.col_indices().numpy();values=cpu_weights.values().numpy()
    projection={}
    for key in ['DNp09_left','DNp09_right']:
        idx=registry['cells'][key]['model_index'];a,b=pointer[idx:idx+2]
        links={int(j):float(w) for j,w in zip(columns[a:b],values[a:b]) if int(j) in lc9_indices and w!=0}
        projection[key]={'connected_lc9_cells':len(links),'signed_weight_sum':sum(links.values()),
                         'connections':[dict(root_id=str(index_to_id[j]),weight=w) for j,w in sorted(links.items())]}
    dump(RUN/'LC9_TO_P9_STRUCTURE.json',projection)
    weights=cpu_weights.to('cuda');del cpu_weights,pointer,columns,values
    model=backend.TorchModel(1,n,backend.DT,backend.MODEL_PARAMS,weights,exc_indices=inputs,device='cuda').eval()
    eager=EagerEngine(model,n)
    report['gpu']={'name':torch.cuda.get_device_name(),'torch':torch.__version__,'cuda':torch.version.cuda}
    report['model']={'neurons':n,'connections':weights._nnz(),'dt_ms':backend.DT,'parameters':backend.MODEL_PARAMS,'inputs':185}
    readout_gpu=torch.tensor(readouts,device='cuda')
    rates={c['name']:torch.tensor(np.load(ROOT/c['rates_file'],allow_pickle=False),device='cuda') for c in conditions}

    def run_blocks(engine, blocks, collect=False):
        traces=[]
        for block in range(blocks):
            engine.block()
            if collect:traces.append(engine.counts[readout_gpu].clone())
            if (block+1)%10==0:
                guard()
                if not engine.healthy():raise RuntimeError('NONFINITE_STATE')
        torch.cuda.synchronize()
        return torch.stack(traces).cpu().numpy() if collect else None

    with torch.no_grad():
        try:
            capture_start=time.perf_counter();graph=GraphEngine(model,n)
            report['capture_seconds']=time.perf_counter()-capture_start
            report['equivalence']=[]
            for name in ['ZERO','HS_LEFT','HS_RIGHT','LC9_200']:
                saved={}
                for tag,engine in [('eager',eager),('graph',graph)]:
                    engine.reset(rates[name],20260923)
                    run_blocks(engine,10)
                    saved[tag]={'counts':engine.counts.cpu().numpy().copy(),**{'state_'+str(i):v.cpu().numpy().copy() for i,v in enumerate(engine.state)}}
                    np.savez_compressed(RUN/('equivalence_'+name+'_'+tag+'.npz'),**saved[tag])
                exact=np.array_equal(saved['eager']['counts'],saved['graph']['counts'])
                differences=[float(np.max(np.abs(saved['eager']['state_'+str(i)]-saved['graph']['state_'+str(i)]))) for i in range(5)]
                ok=exact and max(differences)<=1e-5
                report['equivalence'].append({'condition':name,'counts_exact':exact,'max_state_abs_errors':differences,'pass':ok})
            report['optimization_accepted']=all(c['pass'] for c in report['equivalence'])
            engine=graph if report['optimization_accepted'] else eager
        except Exception as exc:
            # Resource/nonfinite/capture exceptions must not be swallowed as a safe fallback.
            report['optimization_accepted']=False;report['optimization_error']=repr(exc)
            dump(RUN/'OPTIMIZATION.json',{k:v for k,v in report.items() if k!='trials'})
            raise
        report['setup_seconds']=time.perf_counter()-setup
        dump(RUN/'OPTIMIZATION.json',{k:v for k,v in report.items() if k!='trials'})
        if report['optimization_accepted']:
            timings={}
            for tag,candidate in [('eager',eager),('cuda_graph',graph)]:
                samples=[]
                for repeat in range(11):
                    candidate.reset(rates['HS_LEFT'],20260923)
                    t=time.perf_counter();run_blocks(candidate,10);elapsed=time.perf_counter()-t
                    if repeat: samples.append(elapsed)
                timings[tag]={'seconds':samples,'median_ms':float(np.median(samples)*1000),'p99_ms':float(np.quantile(samples,.99)*1000)}
            report['timings']=timings
            report['median_speedup']=timings['eager']['median_ms']/timings['cuda_graph']['median_ms']
        report['photo_backend']='cuda_graph' if report['optimization_accepted'] else 'upstream_eager_fallback'
        for condition in conditions:
            for seed in [20260923,20260924,20260925]:
                name=condition['name'];trial_id=name+'__'+str(seed)
                engine.reset(rates[name],seed)
                t=time.perf_counter();trace=run_blocks(engine,50,collect=True);elapsed=time.perf_counter()-t
                counts=engine.counts.cpu().numpy().copy()
                np.save(RUN/(trial_id+'_counts.npy'),counts,allow_pickle=False)
                np.save(RUN/(trial_id+'_readout_trace.npy'),trace,allow_pickle=False)
                readout={registry['cells'][k]['root_id']:int(counts[registry['cells'][k]['model_index']]) for k in registry['readout_keys']}
                decoder=IntentDecoder(registry,profile,session_id=trial_id,clock_id='OFFLINE_PHOTO_CLOCK',model_identity=report['protocol_sha256'])
                intent=decoder.decode(readout,window_s=.5,session_id=trial_id,sequence=1,source_ns=1_000_000_000,now_ns=1_000_000_000,clock_id='OFFLINE_PHOTO_CLOCK',model_identity=report['protocol_sha256'],brain_healthy=True)
                order=np.argsort(-counts,kind='stable')[:20]
                row={'trial_id':trial_id,'condition':name,'seed':seed,'simulated_ms':500,'wall_seconds':elapsed,
                     'all_spikes':int(counts.sum()),'active_neurons':int(np.count_nonzero(counts)),
                     'lc9_spikes':int(counts[lc9_indices].sum()),
                     'readout_counts':{k:int(counts[registry['cells'][k]['model_index']]) for k in registry['readout_keys']},
                     'top20':[dict(labels[int(i)],model_index=int(i),spikes=int(counts[i])) for i in order if counts[i]>0],
                     'shadow_intent':intent,'hardware_admission_tested':False,
                     'counts_file':trial_id+'_counts.npy','counts_sha256':sha(RUN/(trial_id+'_counts.npy')),
                     'trace_file':trial_id+'_readout_trace.npy','trace_sha256':sha(RUN/(trial_id+'_readout_trace.npy'))}
                report['trials'].append(row)
                dump(RUN/'STATUS.json',report)
                print(json.dumps({'trial':trial_id,'spikes':row['all_spikes'],'p9':row['readout_counts']['DNp09_left']+row['readout_counts']['DNp09_right'],'seconds':elapsed}),flush=True)
        assert len(report['trials'])==75
        report['peak_cuda_allocated_bytes']=torch.cuda.max_memory_allocated()
        report['peak_cuda_reserved_bytes']=torch.cuda.max_memory_reserved()
        report['resources_end']=guard()
        report['status']='COMPLETE_OFFLINE_PROBE'
        dump(RUN/'RESULTS.json',report)
        dump(RUN/'STATUS.json',report)
except Exception as exc:
    report['status']='FAIL';report['error']=repr(exc)
    dump(RUN/'RESULTS.json',report);dump(RUN/'STATUS.json',report)
    raise
