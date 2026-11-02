"""Encoders, registry and decoders: the parts of the fly pipeline that run without a GPU."""
import math

import numpy as np

from flyhead import paths
from flyhead.fly.decoders.loom import DECODERS, decode, make_decoder
from flyhead.fly.encoders.eeg import Encoder, layout
from flyhead.fly.encoders.lidar_loom import LidarRetinaV3, input_indices, rates_vector


def test_registry_identity():
    reg = paths.load_registry()
    assert reg['dataset'] == 'FlyWire783' and reg['model_neurons'] == 138639
    assert reg['counts'] == {'LC4': 104, 'LPLC2': 210, 'LC9': 179, 'DNp01': 2, 'DNp02': 2, 'DNp04': 2,
                             'DNp06': 2, 'DNp09': 2, 'DNp11': 2, 'DNa01': 2, 'DNa02': 2, 'MDN': 4}
    idx = input_indices(reg)
    assert len(idx) == len(set(idx)) == 493
    out = [c['model_index'] for cells in reg['readouts'].values() for c in cells]
    assert not set(idx) & set(out)
    assert all(0 <= i < reg['model_neurons'] for i in idx + out)
    # the calibration flags must stay explicit: side tables are not assumed
    assert reg['field_to_eye_assignment_validated'] is False and reg['robot_yaw_sign_calibrated'] is False


def wall_points(dist, side=0.0, width=1.0):
    """Body-frame points of a short wall `dist` ahead (side > 0: to the left)."""
    y = np.linspace(-width / 2, width / 2, 40) + side
    return np.c_[np.full_like(y, dist), y]


def test_retina_still_scene_has_no_loom():
    retina = LidarRetinaV3()
    for k in range(20):
        rates, _ = retina.step(wall_points(1.5), 0.0, k * 0.1, (0.0, 0.0))
    assert rates[('LC4', 'left')] == 0.0 and rates[('LC4', 'right')] == 0.0
    assert rates[('LC9', 'left')] > 0.0                  # free space ahead drives LC9


def test_retina_approach_on_left_looms_left():
    retina = LidarRetinaV3()
    for k in range(20):                                   # object 0.6 m to the left, approaching at 0.5 m/s
        d = 2.0 - 0.05 * k
        pts = np.c_[np.full(20, d * math.cos(math.radians(45))), np.linspace(-0.15, 0.15, 20) + d * math.sin(math.radians(45))]
        rates, feats = retina.step(pts, 0.0, k * 0.1, (0.0, 0.0))
    assert rates[('LC4', 'left')] > 0.0
    assert rates[('LC4', 'right')] == 0.0


def test_rates_vector_order():
    reg = paths.load_registry()
    v = rates_vector(reg, {('LC4', 'left'): 10.0, ('LC9', 'right'): 5.0})
    assert v.shape == (493,) and v.dtype == np.float32
    lc4 = reg['inputs']['LC4']
    assert all(v[i] == (10.0 if c['anatomical_side'] == 'left' else 0.0) for i, c in enumerate(lc4))


def test_decoder_v1_states():
    assert decode({})['state'] == 'HOLD'
    assert decode({('DNp09', 'left'): 60.0, ('DNp09', 'right'): 60.0})['state'] == 'FORWARD'
    esc = decode({('DNp01', 'left'): 200.0, ('DNp01', 'right'): 200.0, ('DNp09', 'left'): 60.0})
    assert esc['state'] == 'ESCAPE'


def test_decoder_factory():
    assert make_decoder(1) is None
    for version in DECODERS:
        d = make_decoder(version)
        intent = d.decode({}, 0.0)
        assert {'state', 'v', 'w'} <= set(intent)
        assert abs(intent['v']) < 1e-9 or intent['state'] not in ('HOLD',)


def test_eeg_encoder_direction_and_rejection():
    e = Encoder()
    assert e.encode([.9, .1], 0, 0., 0.)[0] == {'left': 32., 'right': 0.}
    assert e.encode([.1, .9], 1, 0., 0.)[0] == {'left': 0., 'right': 32.}
    assert e.encode([.1, .9], 1, 0., 0.)[1] == 'sequence_rejected'
    for p, t, now, on in [([.5, .5], 0., 0., True), ([1., 0.], 0., 1., True), ([1., 0.], 1., 0., True),
                          ([1., 0.], 0., 0., False), ([float('nan'), 0.], 0., 0., True)]:
        assert Encoder().encode(p, 0, t, now, on)[0] == {'left': 0., 'right': 0.}


def test_eeg_layout_adds_dna02():
    reg = paths.load_registry()
    indices, original, cells = layout(reg)
    assert indices[:len(original)] == original and len(indices) == len(original) + 2
    assert cells['right']['root_id'] == '720575940604737708' and cells['right']['model_index'] == 904
