from pathlib import Path
import json
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

class InputTests(unittest.TestCase):
    def setUp(self):
        self.reg=json.loads((ROOT/'config/readout_registry.json').read_text())
        self.lc9=json.loads((ROOT/'config/startup_registry.json').read_text())
        self.conditions=json.loads((ROOT/'config/conditions.json').read_text())

    def test_unique_cells(self):
        self.assertEqual(len(self.lc9['lc9']),179)
        self.assertEqual(len({x['model_index'] for x in self.lc9['lc9']}),179)
        self.assertTrue(all(x['cell_type']=='LC9' for x in self.lc9['lc9']))

    def test_no_direct_behavior_stimulation(self):
        inputs={x['model_index'] for x in self.lc9['lc9']}|{self.reg['cells'][k]['model_index'] for k in self.reg['visual_input_keys']}
        readout={self.reg['cells'][k]['model_index'] for k in self.reg['readout_keys']}
        self.assertFalse(inputs&readout)
        self.assertEqual(len(inputs),185)

    def test_all_rates_valid_and_only_declared_inputs(self):
        inputs={x['model_index'] for x in self.lc9['lc9']}|{self.reg['cells'][k]['model_index'] for k in self.reg['visual_input_keys']}
        for c in self.conditions:
            rates=np.load(ROOT/c['rates_file'],allow_pickle=False)
            self.assertEqual(rates.shape,(138639,))
            self.assertTrue(np.isfinite(rates).all())
            self.assertTrue(0<=rates.min()<=rates.max()<=200)
            self.assertFalse(set(np.flatnonzero(rates))-inputs)

    def test_complete_factorial(self):
        self.assertEqual(len(self.conditions),25)
        names={c['name'] for c in self.conditions}
        for photo in ['china','flower']:
            for d in ['STATIC','LEFT','RIGHT']:
                for b in ['HS_ONLY','LC9_ONLY','COMBINED']:
                    self.assertIn(photo+'_'+d+'_'+b,names)

    def test_static_and_motion_separation(self):
        for c in self.conditions:
            if c['metadata'].get('direction')=='STATIC' and c['metadata'].get('photo')!='blank':
                self.assertTrue(all(f['horizontal_shift_px']==0 for f in c['metadata']['hs_features'].values()))

    def test_blank_is_zero(self):
        c=next(c for c in self.conditions if c['name']=='blank_STATIC_COMBINED')
        self.assertFalse(np.any(np.load(ROOT/c['rates_file'],allow_pickle=False)))
        self.assertFalse(c['metadata']['hs_valid'])

    def test_hs_ablation(self):
        hs=[self.reg['cells'][k]['model_index'] for k in self.reg['visual_input_keys']]
        for c in self.conditions:
            if c['name'].endswith('LC9_ONLY'):
                self.assertFalse(np.any(np.load(ROOT/c['rates_file'],allow_pickle=False)[hs]))

    def test_lc9_ablation(self):
        indices=[x['model_index'] for x in self.lc9['lc9']]
        for c in self.conditions:
            if c['name'].endswith('HS_ONLY'):
                self.assertFalse(np.any(np.load(ROOT/c['rates_file'],allow_pickle=False)[indices]))

if __name__=='__main__':unittest.main(verbosity=2)
