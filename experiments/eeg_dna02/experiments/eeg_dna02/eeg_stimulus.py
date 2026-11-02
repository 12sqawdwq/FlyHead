"""Offline EEG stimulus encoder. No socket, ROS, or actuator imports."""
import math

class Encoder:
    def __init__(self, gain_hz=40.0, threshold=0.8, max_age_s=0.5):
        if not 0 <= gain_hz <= 200 or not .5 < threshold <= 1 or not 0 < max_age_s <= 1:
            raise ValueError('Invalid encoder configuration')
        self.gain, self.threshold, self.max_age = gain_hz, threshold, max_age_s
        self.last_seq = -1

    def encode(self, probabilities, seq, source_t, now, enabled=True):
        zero = dict(left=0.0, right=0.0)
        if type(seq) is not int or seq <= self.last_seq:
            return zero, 'sequence_rejected'
        self.last_seq = seq
        if (not isinstance(probabilities, (list, tuple)) or len(probabilities) != 2
            or any(type(p) not in (int,float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)
            or abs(sum(probabilities)-1) > 1e-4):
            return zero, 'invalid_probability'
        if any(type(t) not in (int,float) or not math.isfinite(t) for t in (source_t,now)) or not 0 <= now-source_t <= self.max_age:
            return zero, 'stale_or_future'
        if not enabled:
            return zero, 'disabled'
        if max(probabilities) < self.threshold:
            return zero, 'uncertain'
        d=probabilities[0]-probabilities[1]
        return dict(left=self.gain*max(d,0),right=self.gain*max(-d,0)), 'accepted'


def layout(registry):
    from retina import input_indices
    original=input_indices(registry)
    cells={c['anatomical_side']:c for c in registry['readouts']['DNa02']}
    assert set(cells)=={'left','right'}
    indices=original+[cells['left']['model_index'],cells['right']['model_index']]
    assert len(set(indices))==len(indices)
    return indices,original,cells
