import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fly_mapping.vision import VisualEncoder
from fly_mapping.commands import IntentDecoder

REGISTRY = json.loads((ROOT / 'config/neuron_registry.json').read_text())
PROFILE = json.loads((ROOT / 'config/mapping_profile.json').read_text())


def texture():
    return np.random.default_rng(71).integers(0, 256, (120, 160), dtype=np.uint8)


class RegistryTests(unittest.TestCase):
    def test_exact_registry_size(self):
        self.assertEqual(len(REGISTRY['visual_input_keys']), 6)
        self.assertEqual(len(REGISTRY['readout_keys']), 8)
        self.assertEqual(len(REGISTRY['cells']), 14)

    def test_no_direct_action_neuron_stimulation(self):
        i = {REGISTRY['cells'][k]['root_id'] for k in REGISTRY['visual_input_keys']}
        o = {REGISTRY['cells'][k]['root_id'] for k in REGISTRY['readout_keys']}
        self.assertFalse(i & o)

    def test_ids_preserve_integer_precision_as_strings(self):
        for row in REGISTRY['cells'].values():
            self.assertIsInstance(row['root_id'], str)
            self.assertGreater(int(row['root_id']), 2 ** 53)
            self.assertTrue(0 <= row['model_index'] < 138639)

    def test_alias_collision_not_merged(self):
        chosen = {row['root_id'] for row in REGISTRY['cells'].values()}
        for row in REGISTRY['excluded_cross_namespace_name_collisions']:
            self.assertNotIn(row['root_id'], chosen)
        self.assertEqual(len(REGISTRY['excluded_cross_namespace_name_collisions']), 4)

    def test_p9_sides_follow_annotation_not_upstream_comment(self):
        self.assertEqual(REGISTRY['cells']['DNp09_left']['root_id'], '720575940635872101')
        self.assertEqual(REGISTRY['cells']['DNp09_right']['root_id'], '720575940627652358')


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.encoder = VisualEncoder(REGISTRY, PROFILE, 'session', 'fixture_clock')
        self.image = texture()

    def consume(self, image, seq=1, source=1_000_000_000, now=None, session='session', clock='fixture_clock'):
        return self.encoder.consume(image, session_id=session, sequence=seq,
                                    source_ns=source, now_ns=source if now is None else now, clock_id=clock)

    def pair(self, dx):
        self.consume(self.image)
        return self.consume(np.roll(self.image, dx, axis=1), seq=2, source=1_100_000_000)

    def test_first_frame_is_not_motion_evidence(self):
        self.assertFalse(self.consume(self.image)['valid'])

    def test_static_texture_is_explicit_tonic_input(self):
        result = self.pair(0)
        self.assertTrue(result['valid'])
        self.assertEqual(set(result['rates_hz'].values()), {5.0})

    def test_left_moving_image_uses_declared_proxy(self):
        result = self.pair(-4)
        self.assertTrue(result['valid'])
        for key, feature in result['features'].items():
            self.assertEqual(feature['horizontal_shift_px'], -4)
            self.assertEqual(feature['input_rate_hz'], 200.0 if key.endswith('_left') else 5.0)

    def test_right_moving_image_uses_declared_proxy(self):
        result = self.pair(4)
        self.assertTrue(result['valid'])
        for key, feature in result['features'].items():
            self.assertEqual(feature['horizontal_shift_px'], 4)
            self.assertEqual(feature['input_rate_hz'], 200.0 if key.endswith('_right') else 5.0)

    def test_no_texture_is_not_free_space(self):
        image = np.zeros_like(self.image)
        self.consume(image)
        result = self.consume(image, seq=2, source=1_100_000_000)
        self.assertFalse(result['valid'])
        self.assertEqual(result['rates_hz'], {})

    def test_stale_frame_fault_does_not_recover(self):
        result = self.consume(self.image, now=1_200_000_001)
        self.assertTrue(result['fault_latched'])
        self.assertFalse(self.consume(self.image, seq=2, source=1_300_000_000)['valid'])

    def test_clock_mismatch_latches(self):
        self.assertTrue(self.consume(self.image, clock='other')['fault_latched'])

    def test_repeated_sequence_latches(self):
        self.consume(self.image)
        self.assertTrue(self.consume(self.image, seq=1, source=1_100_000_000)['fault_latched'])

    def test_long_frame_gap_latches(self):
        self.consume(self.image)
        self.assertTrue(self.consume(self.image, seq=2, source=1_300_000_000)['fault_latched'])

    def test_nan_image_latches(self):
        image = self.image.astype(np.float32); image[0, 0] = np.nan
        self.assertTrue(self.consume(image)['fault_latched'])

    def test_wrong_shape_latches(self):
        self.assertTrue(self.consume(np.zeros((4, 4)))['fault_latched'])

    def test_ragged_array_latches(self):
        self.assertTrue(self.consume([[1, 2], [3]])['fault_latched'])

    def test_complex_image_latches(self):
        self.assertTrue(self.consume(self.image.astype(np.complex64))['fault_latched'])

    def test_rgb_input(self):
        rgb = np.repeat(self.image[:, :, None], 3, axis=2)
        self.consume(rgb)
        self.assertTrue(self.consume(np.roll(rgb, 4, axis=1), seq=2, source=1_100_000_000)['valid'])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.decoder = IntentDecoder(REGISTRY, PROFILE, session_id='session', clock_id='fixture_clock', model_identity='locked-model')
        self.counts = {REGISTRY['cells'][key]['root_id']: 0 for key in REGISTRY['readout_keys']}

    def decode(self, **updates):
        args = dict(window_s=0.1, session_id='session', sequence=1,
                    source_ns=1_000_000_000, now_ns=1_000_000_000,
                    clock_id='fixture_clock', model_identity='locked-model', brain_healthy=True)
        args.update(updates)
        return self.decoder.decode(self.counts, **args)

    def set_count(self, key, count):
        self.counts[REGISTRY['cells'][key]['root_id']] = count

    def test_silent_brain_holds(self):
        result = self.decode()
        self.assertEqual(result['state'], 'HOLD')
        self.assertEqual(result['shadow_forward_m_s'], 0)

    def test_forward_from_bilateral_p9_only(self):
        self.set_count('DNp09_left', 10); self.set_count('DNp09_right', 10)
        result = self.decode()
        self.assertEqual(result['state'], 'EXPLORE')
        self.assertAlmostEqual(result['shadow_forward_m_s'], 0.1)
        self.assertFalse(result['publish_allowed'])

    def test_left_dna02_yields_candidate_left_turn(self):
        self.set_count('DNa02_left', 10)
        self.assertEqual(self.decode()['state'], 'TURN_LEFT')

    def test_right_dna02_yields_candidate_right_turn(self):
        self.set_count('DNa02_right', 10)
        self.assertEqual(self.decode()['state'], 'TURN_RIGHT')

    def test_diagnostics_do_not_trigger_motion_or_jump(self):
        for key in ['DNa01_left', 'DNa01_right', 'DNp01_left', 'DNp01_right']:
            self.set_count(key, 100)
        result = self.decode()
        self.assertEqual(result['state'], 'HOLD')
        self.assertIsNone(result['ros_motion_command'])

    def test_missing_readout_is_not_zero(self):
        self.counts.pop(next(iter(self.counts)))
        self.assertEqual(self.decode()['state'], 'FAULT_HOLD')

    def test_stale_result_latches(self):
        self.assertEqual(self.decode(now_ns=1_101_000_000)['state'], 'FAULT_HOLD')
        self.assertEqual(self.decode(sequence=2, source_ns=1_200_000_000, now_ns=1_200_000_000)['state'], 'FAULT_HOLD')

    def test_wrong_model_identity_latches(self):
        self.assertEqual(self.decode(model_identity='other')['state'], 'FAULT_HOLD')

    def test_unhealthy_brain_holds(self):
        self.assertEqual(self.decode(brain_healthy=False)['state'], 'FAULT_HOLD')

    def test_invalid_visual_input_suppresses_intent(self):
        self.set_count('DNp09_left', 10)
        self.assertEqual(self.decode(input_valid=False)['state'], 'HOLD')

    def test_excessive_or_noninteger_count_rejected(self):
        self.set_count('DNa02_left', 1001)
        self.assertEqual(self.decode()['state'], 'FAULT_HOLD')

    def test_repeated_result_rejected(self):
        self.decode()
        self.assertEqual(self.decode()['state'], 'FAULT_HOLD')

    def test_command_bounds(self):
        self.set_count('DNp09_left', 1000); self.set_count('DNa02_left', 1000)
        result = self.decode()
        self.assertEqual(result['shadow_forward_m_s'], 0.1)
        self.assertEqual(result['shadow_yaw_rad_s'], 0.3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
