from pathlib import Path
import json,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parent
r=json.loads((ROOT/'run_001/RESULTS.json').read_text())
assert r['status']=='COMPLETE_TECHNICAL_VALIDATION'
assert r['protocol_sha256']==hashlib.sha256((ROOT/'protocol_lock.json').read_bytes()).hexdigest()
rows=[]
for name in ['ZERO','HS_LEFT','HS_RIGHT','LC9_200','china_STATIC_COMBINED','flower_STATIC_COMBINED']:
 with np.load(ROOT/'run_001'/(name+'_reference.npz'),allow_pickle=False) as a,np.load(ROOT/'run_001'/(name+'_event.npz'),allow_pickle=False) as b:
  assert a['counts'].shape==b['counts'].shape==(138639,)
  exact=np.array_equal(a['counts'],b['counts'])
  errors=[]
  for i in range(5):
   k='state_'+str(i);assert np.isfinite(a[k]).all() and np.isfinite(b[k]).all()
   errors.append(float(np.abs(a[k]-b[k]).max()))
  rows.append({'condition':name,'counts_exact':exact,'state_errors':errors,'pass':exact and max(errors)<=1e-5})
assert r['accepted']==all(x['pass'] for x in rows)
assert r['integer_exactness_guard']['all_weights_integral']
assert r['integer_exactness_guard']['max_absolute_postsynaptic_weight_sum']<2**24
out={'status':'PASS_ARTIFACT_VALIDATION','event_backend_accepted':r['accepted'],'checks':rows,'live_robot_qualified':False}
(ROOT/'evidence/VALIDATION.json').write_bytes((json.dumps(out,indent=2)+'\n').encode())
print(json.dumps({'status':out['status'],'event_backend_accepted':r['accepted']}))
