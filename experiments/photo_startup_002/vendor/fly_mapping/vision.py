"""Explicit engineered six-HS input proxy, not reconstructed fly retinotopy."""
import copy
import math
import numpy as np


class VisualEncoder:
    def __init__(self, registry, profile, session_id, clock_id):
        if not session_id or not clock_id:
            raise ValueError('session and clock identity required')
        if profile['mode'] != 'SHADOW_ONLY' or profile['publish_motion']:
            raise ValueError('only shadow configuration is implemented')
        self.registry = copy.deepcopy(registry)
        self.profile = copy.deepcopy(profile['vision'])
        self.session_id = session_id
        self.clock_id = clock_id
        self.previous = None
        self.previous_seq = None
        self.previous_ns = None
        self.fault = None

    def _empty(self, seq, source_ns, reason, fault=False):
        if fault:
            self.fault = reason
        return {'session_id': self.session_id, 'sequence': seq, 'source_ns': source_ns,
                'clock_id': self.clock_id, 'valid': False, 'fault_latched': bool(self.fault),
                'reason': self.fault or reason, 'rates_hz': {}, 'features': {},
                'encoding': 'ENGINEERED_HS_MOTION_PROXY', 'motion_output': None}

    @staticmethod
    def _motion(previous, current, max_shift, minimum_std):
        h, w = previous.shape
        # Every candidate uses the same interior support; no padding or wrap cues.
        margin = max_shift
        now = current[:, margin:w - margin]
        if float(now.std()) < minimum_std:
            return 0, 0.0
        a = now - now.mean()
        candidates = []
        for dx in range(-max_shift, max_shift + 1):
            old = previous[:, margin - dx:w - margin - dx]
            b = old - old.mean()
            denominator = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
            correlation = float(np.sum(a * b) / denominator) if denominator > 1e-12 else 0.0
            candidates.append((correlation, -abs(dx), dx))
        correlation, _, dx = max(candidates)
        return dx, correlation

    def consume(self, image, *, session_id, sequence, source_ns, now_ns, clock_id):
        if self.fault:
            return self._empty(sequence, source_ns, self.fault)
        if session_id != self.session_id or clock_id != self.clock_id:
            return self._empty(sequence, source_ns, 'identity_or_clock_mismatch', True)
        if any(type(value) is not int for value in [sequence, source_ns, now_ns]) or sequence < 0 or source_ns < 0:
            return self._empty(sequence, source_ns, 'invalid_sequence_or_time', True)
        if source_ns > now_ns or now_ns - source_ns > self.profile['max_source_age_ms'] * 1_000_000:
            return self._empty(sequence, source_ns, 'future_or_stale_frame', True)
        if self.previous_seq is not None and (sequence <= self.previous_seq or source_ns <= self.previous_ns):
            return self._empty(sequence, source_ns, 'repeated_or_reordered_frame', True)
        try:
            array = np.asarray(image)
        except (TypeError, ValueError):
            return self._empty(sequence, source_ns, 'malformed_image_array', True)
        expected = (self.profile['height'], self.profile['width'])
        if array.shape not in [expected, expected + (3,)]:
            return self._empty(sequence, source_ns, 'invalid_image_shape', True)
        if not (np.issubdtype(array.dtype, np.integer) or np.issubdtype(array.dtype, np.floating)) or not np.isfinite(array).all():
            return self._empty(sequence, source_ns, 'nonfinite_or_nonnumeric_image', True)
        if array.min() < 0 or array.max() > 255:
            return self._empty(sequence, source_ns, 'image_range_not_uint8_scale', True)
        grey = array.astype(np.float32) / 255.0
        if grey.ndim == 3:
            grey = grey @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        if self.previous_ns is not None and source_ns - self.previous_ns > self.profile['max_frame_gap_ms'] * 1_000_000:
            return self._empty(sequence, source_ns, 'frame_gap_exceeded', True)
        old = self.previous
        old_ns = self.previous_ns
        self.previous = grey.copy()
        self.previous_seq = sequence
        self.previous_ns = source_ns
        if old is None:
            return self._empty(sequence, source_ns, 'awaiting_second_frame')
        dt_s = (source_ns - old_ns) / 1e9
        h, w = grey.shape
        features, rates = {}, {}
        for band, cell_type in enumerate(self.profile['band_types']):
            y0, y1 = band * h // 3, (band + 1) * h // 3
            for side_index, side in enumerate(['left', 'right']):
                x0, x1 = side_index * w // 2, (side_index + 1) * w // 2
                dx, quality = self._motion(old[y0:y1, x0:x1], grey[y0:y1, x0:x1],
                                           self.profile['max_shift_px'], self.profile['minimum_patch_std'])
                key = cell_type + '_' + side
                if quality < self.profile['minimum_correlation']:
                    return self._empty(sequence, source_ns, 'insufficient_motion_texture')
                preferred = self.profile['preferred_dx_sign_' + side]
                # Normalize pixel speed to 40 px/s, the 4px / 100ms design reference.
                motion = np.clip(preferred * dx / dt_s / 40.0, 0.0, 1.0)
                rate = self.profile['baseline_hz'] + motion * (self.profile['max_rate_hz'] - self.profile['baseline_hz'])
                neuron_id = self.registry['cells'][key]['root_id']
                rates[neuron_id] = float(rate)
                features[key] = {'horizontal_shift_px': dx, 'velocity_px_s': dx / dt_s,
                                 'correlation': quality, 'input_rate_hz': float(rate)}
        return {'session_id': session_id, 'sequence': sequence, 'source_ns': source_ns,
                'clock_id': clock_id, 'valid': True, 'fault_latched': False, 'reason': None,
                'rates_hz': rates, 'features': features,
                'encoding': 'ENGINEERED_HS_MOTION_PROXY', 'motion_output': None}
