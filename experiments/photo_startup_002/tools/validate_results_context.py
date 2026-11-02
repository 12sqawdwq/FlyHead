"""CPU-only independent full-count, state equivalence, trajectory and arithmetic checks."""
from pathlib import Path
import hashlib
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'run_003'
r=json.loads((RUN/'RESULTS.json').read_text(encoding='utf-8'))
reg=json.loads((ROOT/'config/readout_registry.json').read_text(encoding='utf-8'))
conditions=json.loads((ROOT/'config/conditions.json').read_text(encoding='utf-8'))
assert r['status']=='COMPLETE_OFFLINE_PROBE'
assert r['protocol_sha256']==hashlib.sha256((ROOT/'protocol_lock_context.json').read_bytes()).hexdigest()
assert r['robot_io'] is False and r['graph_cropped'] is False and r['real_video'] is False
assert (r['model']['neurons'],r['model']['connections'])==(138639,15091983)
assert {(x['condition'],x['seed']) for x in r['trials']}=={(c['name'],seed) for c in conditions for seed in [20260923,20260924,20260925]}
assert len(r['trials'])==75
equivalence=[]
for name in ['ZERO','HS_LEFT','HS_RIGHT','LC9_200']:
    with np.load(RUN/('equivalence_'+name+'_eager.npz'),allow_pickle=False) as a, np.load(RUN/('equivalence_'+name+'_graph.npz'),allow_pickle=False) as b:
        exact=np.array_equal(a['counts'],b['counts'])
        delta=[]
        for i in range(5):
            key='state_'+str(i)
            assert np.isfinite(a[key]).all() and np.isfinite(b[key]).all()
            delta.append(float(np.abs(a[key]-b[key]).max()))
        passed=exact and max(delta)<=1e-5
        equivalence.append({'condition':name,'counts_exact':exact,'max_state_abs_errors':delta,'pass':passed})
assert r['optimization_accepted']==all(x['pass'] for x in equivalence)
assert r['photo_backend']==('cuda_graph' if r['optimization_accepted'] else 'upstream_eager_fallback')
for trial in r['trials']:
    for field in ['counts','trace']:
        path=RUN/trial[field+'_file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==trial[field+'_sha256']
    counts=np.load(RUN/trial['counts_file'],allow_pickle=False)
    trace=np.load(RUN/trial['trace_file'],allow_pickle=False)
    assert counts.shape==(138639,) and counts.dtype==np.int32 and 0<=counts.min()<=counts.max()<=5000
    assert trace.shape==(50,8) and (np.diff(trace,axis=0)>=0).all()
    assert int(counts.sum())==trial['all_spikes']
    assert int(np.count_nonzero(counts))==trial['active_neurons']
    for j,key in enumerate(reg['readout_keys']):
        value=int(counts[reg['cells'][key]['model_index']])
        assert value==trial['readout_counts'][key]==int(trace[-1,j])
    c=trial['readout_counts']
    # Counts / 0.5s = Hz; original readout reference stays 100Hz.
    v=min((c['DNp09_left']+c['DNp09_right'])/100,1)*.1
    w=float(np.clip((c['DNa02_left']-c['DNa02_right'])/50,-1,1))*.3
    assert abs(trial['shadow_intent']['shadow_forward_m_s']-v)<1e-12
    assert abs(trial['shadow_intent']['shadow_yaw_rad_s']-w)<1e-12
    assert trial['shadow_intent']['publish_allowed'] is False
    if trial['condition']=='ZERO':assert trial['all_spikes']==0
summary=[]
for condition in conditions:
    group=[t for t in r['trials'] if t['condition']==condition['name']]
    summary.append({'condition':condition['name'],'n':len(group),'mean_all_spikes':float(np.mean([x['all_spikes'] for x in group])),
        'mean_readout_hz':{key:float(np.mean([x['readout_counts'][key]/.5 for x in group])) for key in reg['readout_keys']},
        'mean_v':float(np.mean([x['shadow_intent']['shadow_forward_m_s'] for x in group])),
        'mean_yaw':float(np.mean([x['shadow_intent']['shadow_yaw_rad_s'] for x in group]))})
result={'status':'PASS_INDEPENDENT_VALIDATION','equivalence':equivalence,'trials':75,
        'photo_backend':r['photo_backend'],'conditions':summary,'real_camera_or_robot_validated':False}
(ROOT/'evidence/VALIDATION_CONTEXT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({'status':result['status'],'trials':75,'optimization_accepted':r['optimization_accepted']}))
