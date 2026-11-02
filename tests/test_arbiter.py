"""Control-ownership arbiter: one motion source at a time (no robot, no GPU)."""
from flyhead.server.arbiter import Arbiter


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make():
    c = Clock()
    return Arbiter(clock=c), c


def test_two_consoles_do_not_take_over_each_other():
    a, c = make()
    assert a.request('nav', client='A', name='console A')[0]
    ok, why, ended = a.request('manual', client='B', name='console B')
    assert not ok and 'console A holds control' in why and a.owner == 'nav'
    assert not a.request('nav', client='B')[0]
    # an explicit take-over transfers control; the running task is not cancelled by it
    previous, ended = a.take_control('B', 'console B')
    assert previous == 'console A' and ended is None and a.owner == 'nav'
    ok, why, ended = a.request('manual', client='B')
    assert ok and ended == 'nav' and a.owner == 'manual'


def test_stop_is_accepted_from_any_console():
    a, c = make()
    a.request('brain', client='A')
    assert a.stop('stop from console B') == 'brain' and a.owner == 'idle'


def test_posture_refused_while_brain_drives():
    a, c = make()
    a.request('brain', client='A')
    ok, why, _ = a.request('posture', client='A')
    assert not ok and 'brain is active' in why and a.owner == 'brain'


def test_brain_commands_ignored_during_posture():
    a, c = make()
    assert a.request('posture', client='A')[0]
    assert not a.submit('brain', 0.1, 0.0)
    assert a.command(0.3) == (0.0, 0.0)


def test_retrace_ends_brain_and_nothing_else_commands():
    a, c = make()
    a.request('brain', client='A')
    a.submit('brain', 0.1, 0.2)
    ok, why, ended = a.request('retrace', client='A')
    assert ok and ended == 'brain'
    assert not a.submit('brain', 0.1, 0.2) and not a.submit('nav', 0.1, 0.0)
    assert a.command(0.3) == (0.0, 0.0)


def test_nav_and_brain_refuse_each_other():
    a, c = make()
    a.request('nav', client='A')
    assert not a.request('brain', client='A')[0]
    a.release('nav', 'arrived')
    assert a.request('brain', client='A')[0]
    assert not a.request('nav', client='A')[0]


def test_manual_takes_over_and_lapses():
    a, c = make()
    a.request('nav', client='A')
    ok, _, ended = a.request('manual', client='A')
    assert ok and ended == 'nav'
    a.submit('manual', 0.2, 0.0)
    assert a.command(0.3) == (0.2, 0.0)
    c.t += 0.4
    assert a.command(0.3) == (0.0, 0.0)          # lease expired
    c.t += 1.0
    assert a.expire() == 'manual' and a.owner == 'idle'


def test_controlling_console_lost_ends_brain_not_nav():
    a, c = make()
    a.request('brain', client='A')
    assert a.client_lost('A') == 'brain' and a.owner == 'idle'
    a.request('nav', client='B')
    assert a.client_lost('B') is None and a.owner == 'nav'
    assert a.client_lost('C') is None           # an observer leaving changes nothing


def test_halt_latches_until_cleared():
    a, c = make()
    a.request('nav', client='A')
    assert a.halt('battery', 'battery 12 %') == 'nav' and a.owner == 'halt'
    ok, why, _ = a.request('manual', client='A')
    assert not ok and 'battery 12 %' in why
    a.halt('fault', 'pipeline fault')
    a.clear('battery')
    assert a.owner == 'halt'                     # still one halt left
    a.clear('fault')
    assert a.owner == 'idle' and a.request('manual', client='A')[0]


def test_release_of_another_owner_is_ignored():
    a, c = make()
    a.request('brain', client='A')
    assert not a.release('nav') and a.owner == 'brain'


def test_posture_times_out():
    a, c = make()
    a.request('posture')
    c.t += a.POSTURE_TIMEOUT_S + 0.1
    assert a.expire() == 'posture' and a.owner == 'idle'


def test_reflex_inside_nav():
    a, c = make()
    a.request('nav', client='A')
    assert a.submit('nav', -0.3, 0.0, reflex=True) and a.status()['reflex']
    assert a.command(0.3) == (-0.3, 0.0)


def test_posture_allowed_during_halt_without_releasing_it():
    a, c = make()
    a.halt('localization', 'waiting for relocalization')
    assert a.request('posture', client='A')[0] and a.owner == 'halt'
    assert a.command(0.3) == (0.0, 0.0)


def test_observer_may_not_change_a_running_task():
    a, c = make()
    a.request('nav', client='A', name='console A')
    assert a.allowed('A')[0] and not a.allowed('B')[0]
