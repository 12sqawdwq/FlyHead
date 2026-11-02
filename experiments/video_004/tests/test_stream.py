from pathlib import Path
import json,sys,unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'vendor')]
from stream_input import StreamInput
REG=json.loads((ROOT/'config/readout_registry.json').read_text())
LC=json.loads((ROOT/'config/startup_registry.json').read_text())
PROFILE=json.loads((ROOT/'config/mapping_profile.json').read_text())
VIDEOS=json.loads((ROOT/'config/videos.json').read_text())

class StreamTests(unittest.TestCase):
 def test_real_frames_and_causal_timestamps(self):
  for v in VIDEOS:
   a=np.load(ROOT/v['frames_file'],allow_pickle=False)
   ts=json.loads((ROOT/v['timestamps_file']).read_text())
   self.assertEqual(a.shape,(80,120,160,3));self.assertEqual(a.dtype,np.uint8)
   self.assertTrue(np.any(a[0]!=a[-1]))
   self.assertTrue(all(x['media_pts_seconds']<=x['replay_seconds']+1e-9 for x in ts))
   self.assertTrue(all(a['index']<b['index'] for a,b in zip(ts,ts[1:])))
 def test_target_set(self):
  e=StreamInput(REG,LC,PROFILE,'s')
  self.assertEqual(len(set(e.input_indices)),185)
  self.assertFalse(set(e.input_indices)&{REG['cells'][k]['model_index'] for k in REG['readout_keys']})
 def test_frozen_motion_zero_after_priming(self):
  image=np.load(ROOT/VIDEOS[0]['frames_file'],allow_pickle=False)[0]
  e=StreamInput(REG,LC,PROFILE,'s');e.encode(image,0,'FROZEN_FIRST')
  rates,meta=e.encode(image,1,'FROZEN_FIRST')
  self.assertTrue(meta['hs_valid']);self.assertTrue(all(x['horizontal_shift_px']==0 for x in meta['features'].values()))
  self.assertTrue(np.all(rates[:6]==5))
 def test_reset_and_continuous_inputs_identical(self):
  image=np.load(ROOT/VIDEOS[0]['frames_file'],allow_pickle=False)
  a=StreamInput(REG,LC,PROFILE,'a');b=StreamInput(REG,LC,PROFILE,'b')
  for k in range(6):self.assertTrue(np.array_equal(a.encode(image[k],k,'CONTINUOUS')[0],b.encode(image[k],k,'RESET_STATE')[0]))
 def test_no_input_tail(self):
  r,m=StreamInput(REG,LC,PROFILE,'s').encode(None,80,'CONTINUOUS')
  self.assertFalse(np.any(r));self.assertFalse(m['frame_present']);self.assertFalse(m['hs_valid'])
 def test_hs_only_removes_lc9(self):
  image=np.load(ROOT/VIDEOS[0]['frames_file'],allow_pickle=False)[0]
  r,_=StreamInput(REG,LC,PROFILE,'s').encode(image,0,'HS_ONLY')
  self.assertFalse(np.any(r[6:]))
 def test_first_frame_not_motion_evidence(self):
  image=np.load(ROOT/VIDEOS[0]['frames_file'],allow_pickle=False)[0]
  _,m=StreamInput(REG,LC,PROFILE,'s').encode(image,0,'CONTINUOUS')
  self.assertFalse(m['hs_valid']);self.assertEqual(m['reason'],'awaiting_second_frame')
 def test_rates_are_bounded(self):
  for v in VIDEOS:
   a=np.load(ROOT/v['frames_file'],allow_pickle=False);e=StreamInput(REG,LC,PROFILE,v['name'])
   for k in range(80):
    r,_=e.encode(a[k],k,'CONTINUOUS')
    self.assertTrue(np.isfinite(r).all() and r.min()>=0 and r.max()<=200)

if __name__=='__main__':unittest.main(verbosity=2)
