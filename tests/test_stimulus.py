"""Stimulus-response monitor (no brain service, no GPU)."""
from flyhead.server.stimulus import StimulusMonitor, QUIET_S


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def feed(m, c, n, state, loom_l=0.0, loom_r=0.0, gf=0.0, static=True):
    out = None
    for _ in range(n):
        m.wcount = getattr(m, 'wcount', 0) + 1
        row = dict(window=m.wcount, intent=dict(state=state, gf_hz=gf, mdn_hz=0.0, p9_hz=5.0, arousal=0.4),
                   inputs_hz={'LC9_left': 10.0, 'LC9_right': 12.0, 'LC4_left': 3.0}, readouts_hz={'GF_left': gf})
        feats = dict(left=dict(loom_rad_s=loom_l, nearest_m=1.2), right=dict(loom_rad_s=loom_r, nearest_m=0.9))
        out = m.update(row, feats, static, 'shadow') or out
        c.t += 0.1
    return out


def test_right_loom_episode_with_escape_latency():
    c = Clock()
    m = StimulusMonitor(clock=c)
    assert feed(m, c, 5, 'EXPLORE') is None and m.current is None
    feed(m, c, 3, 'EXPLORE', loom_r=0.08)                 # stimulus on, no response yet
    feed(m, c, 4, 'ESCAPE_PROGRAM', loom_r=0.12, gf=120)  # response 0.3 s after onset
    e = feed(m, c, int(QUIET_S / 0.1) + 3, 'EXPLORE')     # quiet long enough to close
    assert e is not None and m.current is None
    assert e['trigger'] == 'stimulus' and e['side'] == 'right' and e['response'] == 'ESCAPE_PROGRAM'
    assert 250 <= e['latency_ms'] <= 350 and e['peak_gf'] == 120 and e['static']
    assert e['states'][:2] == ['EXPLORE', 'ESCAPE_PROGRAM']
    assert m.status()['episodes'][0]['n'] == 1


def test_spontaneous_defensive_state_has_no_latency():
    c = Clock()
    m = StimulusMonitor(clock=c)
    feed(m, c, 4, 'FREEZE')
    e = feed(m, c, int(QUIET_S / 0.1) + 3, 'EXPLORE')
    assert e['trigger'] == 'spontaneous' and e['response'] == 'FREEZE' and e['latency_ms'] is None
    assert e['side'] is None


def test_live_fields_and_static_flag():
    c = Clock()
    m = StimulusMonitor(clock=c)
    feed(m, c, 1, 'EXPLORE', loom_l=0.02, static=False)
    live = m.status()['live']
    assert live['lc_l'] == 13.0 and live['lc_r'] == 12.0 and live['static'] is False
    assert m.status()['trace'][-1][3] == 'EXPLORE'


def test_same_window_counted_once():
    c = Clock()
    m = StimulusMonitor(clock=c)
    row = dict(window=7, intent=dict(state='EXPLORE'))
    m.update(row, {}, True, 'shadow')
    m.update(row, {}, True, 'shadow')
    assert len(m.status()['trace']) == 1
