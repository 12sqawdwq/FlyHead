"""Neural counts -> bounded shadow intent. No ROS publisher or device calls."""
import copy
import math


class IntentDecoder:
    def __init__(self, registry, profile, *, session_id, clock_id, model_identity):
        if profile['mode'] != 'SHADOW_ONLY' or profile['publish_motion']:
            raise ValueError('physical publishing is not implemented')
        if not session_id or not clock_id or not model_identity:
            raise ValueError('session, clock, and model identities required')
        self.registry = copy.deepcopy(registry)
        self.config = copy.deepcopy(profile['readout'])
        self.session_id = session_id
        self.clock_id = clock_id
        self.model_identity = model_identity
        self.last_sequence = None
        self.last_source_ns = None
        self.fault = None

    def _result(self, sequence, source_ns, state, forward=0.0, yaw=0.0, reason=None, rates=None):
        return {'session_id': self.session_id, 'sequence': sequence, 'source_ns': source_ns,
                'clock_id': self.clock_id, 'model_identity': self.model_identity,
                'state': state, 'shadow_forward_m_s': float(forward), 'shadow_yaw_rad_s': float(yaw),
                'publish_allowed': False, 'ros_motion_command': None,
                'hardware_calibration_complete': False,
                'reason': reason, 'readout_rates_hz': rates or {}}

    def _fail(self, sequence, source_ns, reason):
        self.fault = reason
        return self._result(sequence, source_ns, 'FAULT_HOLD', reason=reason)

    def decode(self, counts, *, window_s, session_id, sequence, source_ns, now_ns,
               clock_id, model_identity, brain_healthy, input_valid=True):
        if self.fault:
            return self._result(sequence, source_ns, 'FAULT_HOLD', reason=self.fault)
        if session_id != self.session_id or clock_id != self.clock_id or model_identity != self.model_identity:
            return self._fail(sequence, source_ns, 'identity_or_clock_mismatch')
        if any(type(v) is not int for v in [sequence, source_ns, now_ns]) or sequence < 0 or source_ns < 0:
            return self._fail(sequence, source_ns, 'invalid_sequence_or_time')
        if source_ns > now_ns or now_ns - source_ns > self.config['max_source_age_ms'] * 1_000_000:
            return self._fail(sequence, source_ns, 'future_or_stale_source')
        if self.last_sequence is not None and (sequence <= self.last_sequence or source_ns <= self.last_source_ns):
            return self._fail(sequence, source_ns, 'reordered_or_repeated_input')
        if brain_healthy is not True:
            return self._fail(sequence, source_ns, 'brain_unhealthy')
        if type(window_s) not in [int, float] or not math.isfinite(window_s) or not 0 < window_s <= 1.0:
            return self._fail(sequence, source_ns, 'invalid_count_window')
        expected = [self.registry['cells'][key]['root_id'] for key in self.registry['readout_keys']]
        if not isinstance(counts, dict) or set(counts) != set(expected):
            return self._fail(sequence, source_ns, 'readout_set_mismatch')
        max_spikes = int(round(window_s / 0.0001))
        for value in counts.values():
            if type(value) is not int or not 0 <= value <= max_spikes:
                return self._fail(sequence, source_ns, 'invalid_spike_count')
        rates = {key: counts[self.registry['cells'][key]['root_id']] / window_s for key in self.registry['readout_keys']}
        self.last_sequence, self.last_source_ns = sequence, source_ns
        if input_valid is not True:
            return self._result(sequence, source_ns, 'HOLD', reason='visual_input_not_ready', rates=rates)
        forward_activity = (rates['DNp09_left'] + rates['DNp09_right']) / 2
        turn_activity = rates['DNa02_left'] - rates['DNa02_right']
        forward = min(max(forward_activity / self.config['reference_rate_hz'], 0.0), 1.0) * self.config['max_forward_m_s']
        yaw = min(max(turn_activity / self.config['reference_rate_hz'], -1.0), 1.0) * self.config['max_yaw_rad_s']
        threshold = self.config['turn_state_threshold_rad_s']
        if yaw > threshold:
            state = 'TURN_LEFT'
        elif yaw < -threshold:
            state = 'TURN_RIGHT'
        elif forward > 0:
            state = 'EXPLORE'
        else:
            state = 'HOLD'
        return self._result(sequence, source_ns, state, forward, yaw, rates=rates)
