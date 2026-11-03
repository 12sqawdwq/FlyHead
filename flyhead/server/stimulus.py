"""Stimulus-response monitor: what the fly brain sees and how it answers, window by window.

Built for the console's Stimulus panel, mainly for a robot standing still. With the robot still, static walls
do not loom, so the retina's looming signal comes from things that move toward it (a person, a box pushed
closer). The monitor keeps

  live      the newest window: looming rate and nearest distance per side, retina input (LC rates per side),
            escape-related readouts (GF, MDN, P9), arousal and the decoded state;
  trace     the last TRACE_S of windows, for the sparkline;
  episodes  one entry per stimulus episode: when it began, what triggered it (a looming stimulus, or a
            defensive state with no stimulus), its side and peak, the first defensive state the brain
            entered and its latency from stimulus onset, the state sequence, and the peak GF / MDN / P9.

It observes only. It never changes a command, and it runs in every brain mode except off. In shadow mode the
robot does not move, so this panel shows the brain's responses to stimuli in isolation.
Values are model outputs: the decoded state of the connectome simulation, not a measured fly.
"""
import time
from collections import deque

LOOM_ON = 0.03          # rad/s: a looming rate at or above this starts a stimulus episode
LOOM_OFF = 0.01         # ... and the episode ends once it stays below this ...
QUIET_S = 1.5           # ... with no defensive state for this long
DEFENSIVE = ('FREEZE', 'ESCAPE_PROGRAM', 'FLEE', 'BACK_OFF')
TRACE_S = 8.0
MAX_EPISODES = 20


def _side_rates(rates, prefix):
    """Sum of input rates (Hz) per side for keys like 'LC9_left'."""
    out = {'left': 0.0, 'right': 0.0}
    for k, v in (rates or {}).items():
        if k.startswith(prefix):
            side = 'left' if k.endswith('left') else 'right' if k.endswith('right') else None
            if side:
                out[side] += float(v or 0.0)
    return out


class StimulusMonitor:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.live = None
        self.trace = deque()
        self.episodes = deque(maxlen=MAX_EPISODES)
        self.current = None
        self.last_window = None
        self.count = 0

    def update(self, row, features, static, mode):
        """One call per control tick; a brain window is processed once (by its window number)."""
        if not row or row.get('window') == self.last_window:
            return None
        self.last_window = row.get('window')
        t = self.clock()
        f = features or {}
        L, R = f.get('left') or {}, f.get('right') or {}
        intent = row.get('intent') or {}
        state = intent.get('state')
        loom_l, loom_r = float(L.get('loom_rad_s') or 0.0), float(R.get('loom_rad_s') or 0.0)
        lc = _side_rates(row.get('inputs_hz'), 'LC')
        reads = row.get('readouts_hz') or {}
        top = sorted(reads.items(), key=lambda kv: -kv[1])[:6]
        self.live = dict(
            t=t, window=row.get('window'), static=bool(static), mode=mode, state=state,
            loom_l=round(loom_l, 3), loom_r=round(loom_r, 3),
            loom_big_l=L.get('loom_big_rad_s'), loom_big_r=R.get('loom_big_rad_s'),
            nearest_l=L.get('nearest_m'), nearest_r=R.get('nearest_m'),
            lc_l=round(lc['left'], 1), lc_r=round(lc['right'], 1),
            gf_hz=intent.get('gf_hz'), mdn_hz=intent.get('mdn_hz'), p9_hz=intent.get('p9_hz'),
            arousal=intent.get('arousal'), readouts=[[k, v] for k, v in top])
        self.trace.append((round(t, 2), round(loom_l, 3), round(loom_r, 3), state,
                           intent.get('gf_hz') or 0.0, intent.get('mdn_hz') or 0.0))
        while self.trace and t - self.trace[0][0] > TRACE_S:
            self.trace.popleft()
        return self._episode(t, loom_l, loom_r, state, intent, static, L, R)

    def _episode(self, t, loom_l, loom_r, state, intent, static, L, R):
        loom = max(loom_l, loom_r)
        defensive = state in DEFENSIVE
        e = self.current
        if e is None:
            if loom < LOOM_ON and not defensive:
                return None
            self.count += 1
            e = self.current = dict(
                n=self.count, start=t, static=bool(static), trigger='stimulus' if loom >= LOOM_ON else 'spontaneous',
                stimulus_at=t if loom >= LOOM_ON else None, side=None, loom_l=0.0, loom_r=0.0, peak_loom=0.0,
                nearest_m=None, states=[], response=None, latency_ms=None, peak_gf=0.0, peak_mdn=0.0,
                peak_p9=0.0, quiet_since=None, end=None)
        if loom >= LOOM_ON and e['stimulus_at'] is None:
            e['stimulus_at'] = t
        e['loom_l'] += loom_l
        e['loom_r'] += loom_r
        e['peak_loom'] = max(e['peak_loom'], loom)
        for side in (L, R):
            d = side.get('nearest_m')
            if d is not None and (e['nearest_m'] is None or d < e['nearest_m']):
                e['nearest_m'] = d
        if state and (not e['states'] or e['states'][-1] != state):
            e['states'].append(state)
        if defensive and e['response'] is None:
            e['response'] = state
            if e['stimulus_at'] is not None:
                e['latency_ms'] = round((t - e['stimulus_at']) * 1000)
        e['peak_gf'] = max(e['peak_gf'], float(intent.get('gf_hz') or 0.0))
        e['peak_mdn'] = max(e['peak_mdn'], float(intent.get('mdn_hz') or 0.0))
        e['peak_p9'] = max(e['peak_p9'], float(intent.get('p9_hz') or 0.0))
        e['static'] = e['static'] and bool(static)
        if loom < LOOM_OFF and not defensive:
            e['quiet_since'] = e['quiet_since'] or t
            if t - e['quiet_since'] >= QUIET_S:
                return self._close(e)
        else:
            e['quiet_since'] = None
        return None

    def _close(self, e):
        e['end'] = e['quiet_since']
        e['duration_s'] = round(e['end'] - e['start'], 2)
        total = e['loom_l'] + e['loom_r']
        e['side'] = None if total <= 0 else ('left' if e['loom_l'] > 1.3 * e['loom_r'] else
                                             'right' if e['loom_r'] > 1.3 * e['loom_l'] else 'both')
        for k in ('loom_l', 'loom_r', 'quiet_since'):
            e.pop(k, None)
        e['peak_loom'] = round(e['peak_loom'], 3)
        self.episodes.appendleft(e)
        self.current = None
        return e

    def status(self):
        cur = None
        if self.current:
            c = self.current
            cur = dict(n=c['n'], start=c['start'], trigger=c['trigger'], peak_loom=round(c['peak_loom'], 3),
                       response=c['response'], latency_ms=c['latency_ms'], states=c['states'][-6:],
                       static=c['static'])
        return dict(live=self.live, trace=list(self.trace), current=cur, episodes=list(self.episodes),
                    thresholds=dict(loom_on=LOOM_ON, loom_off=LOOM_OFF, quiet_s=QUIET_S, defensive=DEFENSIVE))
