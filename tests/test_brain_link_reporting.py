"""BrainLink.command with sessions that do and do not report (no brain service, no GPU).

Regression: stage 6 (flyhead.sim.reflex_sim) crashed with AttributeError the first time a stimulus
episode closed, because its session stub had no record_telemetry / event (added with the Stimulus panel).
"""
import types

from flyhead.server.brain_link import BrainLink
from flyhead.server.stimulus import QUIET_S, StimulusMonitor
from test_stimulus import Clock, feed


def real_episode():
    c = Clock()
    m = StimulusMonitor(clock=c)
    feed(m, c, 3, 'EXPLORE', loom_r=0.08)
    feed(m, c, 4, 'ESCAPE_PROGRAM', loom_r=0.12, gf=120)
    e = feed(m, c, int(QUIET_S / 0.1) + 3, 'EXPLORE')
    assert e is not None
    return e


def link_with_episode(session):
    link = BrainLink(session)
    ep = real_episode()
    link.stim.update = lambda *a, **k: ep            # the monitor closes an episode on this cycle
    return link


def test_session_without_reporting_does_not_break_the_command_path():
    link = link_with_episode(types.SimpleNamespace(nav=None))
    v, w, rec = link.command(0.0)
    assert (v, w) == (0.0, 0.0) and rec['withheld'] == 'no fresh brain window'
    assert 'AttributeError' in link.last['stimulus_error']


def test_episode_is_recorded_and_announced():
    seen = dict(telemetry=[], events=[])
    session = types.SimpleNamespace(nav=None, record_telemetry=seen['telemetry'].append,
                                    event=lambda text, **kw: seen['events'].append(text))
    link = link_with_episode(session)
    link.command(0.0)
    assert seen['telemetry'][0]['type'] == 'stimulus_episode'
    assert seen['events'][0].startswith('Stimulus 1: stimulus right') and 'ESCAPE_PROGRAM' in seen['events'][0]
    assert 'stimulus_error' not in link.last
