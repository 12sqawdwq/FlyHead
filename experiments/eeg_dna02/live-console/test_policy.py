import importlib.util,pathlib,unittest,time
P=pathlib.Path(__file__).with_name('robot-policy.py')
spec=importlib.util.spec_from_file_location('policy',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PolicyTests(unittest.TestCase):
 def test_modes_exclusive(self):
  a=m.Arbiter();a.switch('eeg')
  with self.assertRaises(ValueError):a.enable('manual',1,True)
  a.enable('eeg',1,True,source='eeg')
  with self.assertRaises(ValueError):a.enable('other',1.01,True,source='eeg')
  a.drive('eeg',1.02,0,.1,True,source='eeg');self.assertEqual(a.output(1.03),(0,.1));self.assertEqual(a.output(1.28),(0,0))
 def test_caps_and_freshness(self):
  a=m.Arbiter();a.switch('eeg');a.enable('e',1,True,source='eeg')
  with self.assertRaises(ValueError):a.drive('e',1.02,0,.11,True,source='eeg')
  self.assertEqual(a.command,(0,0))
  s=m.FreshSession(0);p=dict(seq=1,ticket=s.ticket);s.accept(p,.1)
  with self.assertRaises(ValueError):s.accept(p,.11)
 def test_switch_stops(self):
  a=m.Arbiter();a.enable('m',1,True);a.drive('m',1.01,0,.1,True);a.switch('eeg');self.assertIsNone(a.owner);self.assertEqual(a.command,(0,0))
if __name__=='__main__':unittest.main()
