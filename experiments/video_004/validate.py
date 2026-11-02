"""Independent CPU validation of every video frame, input, counter and readout."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parent;RUN=ROOT/'run_001'
r=json.loads((RUN/'RESULTS.json').read_text())
reg=json.loads((ROOT/'config/readout_registry.json').read_text());keys=reg['readout_keys'];indices=[reg['cells'][k]['model_index'] for k in keys]
assert r['status']=='COMPLETE_STATEFUL_VIDEO_PROBE'
assert r['protocol_sha256']==hashlib.sha256((ROOT/'protocol_lock.json').read_bytes()).hexdigest()
assert r['robot_io'] is False and r['model']['neurons']==138639 and r['model']['connections']==15091983
expected={(v,a,s) for v in ['tum_fr1_xyz','tum_fr1_desk'] for a in ['CONTINUOUS','FROZEN_FIRST','RESET_STATE','HS_ONLY'] for s in [20260923,20260924]}
assert len(r['episodes'])==16 and {(x['video'],x['arm'],x['seed']) for x in r['episodes']}==expected
eq=[]
for v in ['tum_fr1_xyz','tum_fr1_desk']:
 with np.load(RUN/('equivalence_'+v+'_reference.npz'),allow_pickle=False) as a,np.load(RUN/('equivalence_'+v+'_event.npz'),allow_pickle=False) as b:
  assert a['counts'].shape==b['counts'].shape==(5,138639)
  assert np.array_equal(a['counts'],b['counts'])
  errors=[float(np.abs(a['state_'+str(i)]-b['state_'+str(i)]).max()) for i in range(5)]
  assert max(errors)<=1e-5
  eq.append({'video':v,'frame_counts_exact':True,'state_errors':errors})
summary=[];rates_by={};first_by={}
for info in r['episodes']:
 e=json.loads((RUN/(info['episode_id']+'.json')).read_text());path=RUN/e['artifact']
 assert hashlib.sha256(path.read_bytes()).hexdigest()==info['artifact_sha256']==e['artifact_sha256']
 assert e['rng_seed_resets']==1 and e['state_resets']==(90 if e['arm']=='RESET_STATE' else 1)
 with np.load(path,allow_pickle=False) as z:
  counts=z['counts'];rates=z['input_rates'];bins=z['readout_bins']
  assert counts.shape==(90,138639) and counts.dtype==np.uint16 and counts.max()<=1000
  assert rates.shape==(90,185) and np.isfinite(rates).all() and rates.min()>=0 and rates.max()<=200
  assert not np.any(rates[80:])
  assert bins.shape==(900,8) and (bins>=0).all()
  assert np.array_equal(bins.reshape(90,10,8).sum(1),counts[:,indices])
  for i in range(5):assert np.isfinite(z['final_state_'+str(i)]).all()
  if e['arm']=='HS_ONLY':assert not np.any(rates[:,6:])
  if e['arm']=='RESET_STATE':assert not np.any(counts[80:])
  rates_by[(e['video'],e['arm'],e['seed'])]=rates.copy();first_by[(e['video'],e['arm'],e['seed'])]=counts[0].copy()
  assert len(e['frames'])==90
  for k,row in enumerate(e['frames']):
   assert row['frame']==k and row['neural_window_start_ms']==100*k and row['neural_window_end_ms']==100*(k+1)
   assert row['all_spikes']==int(counts[k].sum()) and row['active_neurons']==int(np.count_nonzero(counts[k]))
   assert row['stimulus']['frame_present']==(k<80)
   c=row['readout_counts']
   for j,key in enumerate(keys):assert c[key]==int(counts[k,indices[j]])
   valid=row['stimulus']['hs_valid'] and k<80
   v=min((c['DNp09_left']+c['DNp09_right'])/20,1)*.1 if valid else 0.
   w=float(np.clip((c['DNa02_left']-c['DNa02_right'])/10,-1,1))*.3 if valid else 0.
   assert abs(row['intent']['shadow_forward_m_s']-v)<1e-12 and abs(row['intent']['shadow_yaw_rad_s']-w)<1e-12
   assert row['intent']['publish_allowed'] is False and row['live_admission'] is False
   if k>=80:assert row['intent']['state']=='HOLD' and row['original_video_source'] is None
   assert row['within_100ms_compute_budget']==(row['processing_ms']<=100)
   assert len(row['state_summary'])==5
   assert all(np.isfinite([x['min'],x['max']]).all() and x['min']<=x['max'] for x in row['state_summary'].values())
  rows=e['frames'][:80]
  features=[feature for row in rows for feature in row['stimulus']['features'].values()]
  summary.append({'episode':e['episode_id'],'video':e['video'],'arm':e['arm'],'seed':e['seed'],
   'mean_readout_hz':{key:float(counts[:80,indices[j]].sum()/8) for j,key in enumerate(keys)},
   'hs_valid_fraction':float(np.mean([x['stimulus']['hs_valid'] for x in rows])),
   'valid_region_search_boundary_fraction':float(np.mean([abs(x['horizontal_shift_px'])==4 for x in features])) if features else None,
   'model_median_ms':float(np.median([x['model_and_health_ms'] for x in rows])),
   'processing_p99_ms':float(np.quantile([x['processing_ms'] for x in rows],.99)),
   'compute_budget_pass_fraction':float(np.mean([x['within_100ms_compute_budget'] for x in rows])),
   'tail_total_spikes':int(counts[80:].sum()),'tail_P9_spikes':int(counts[80:,indices[2:4]].sum()),
   'last_tail_frame_spikes':int(counts[-1].sum()),'recorded_video_spikes':int(counts[:80].sum())})
for v,a,s in expected:
 if a=='RESET_STATE':
  assert np.array_equal(rates_by[(v,a,s)],rates_by[(v,'CONTINUOUS',s)])
  assert np.array_equal(first_by[(v,a,s)],first_by[(v,'CONTINUOUS',s)])
result={'status':'PASS_INDEPENDENT_VIDEO_VALIDATION','episodes':16,'windows':1440,'dynamic_equivalence':eq,'summary':summary,'live_robot_qualified':False}
(ROOT/'evidence/VALIDATION.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
print(json.dumps({'status':result['status'],'episodes':16,'windows':1440}))
