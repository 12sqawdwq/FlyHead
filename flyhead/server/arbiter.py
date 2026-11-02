"""Control-ownership arbiter: exactly one source may command motion at a time.

Owners
  idle     nothing commands motion; the server sends zero
  manual   teleoperation from the controlling console
  nav      a navigation task (goal, explore, return home, tour and lap series); a fly-brain reflex
           may command inside it while it holds the task
  brain    fly-brain drive (Roam)
  retrace  the robot returns along its driven path; the bridge drives, the server sends zero
  posture  a stand or crouch transition; no motion until the chassis confirms or the request fails
  halt     latched safety stop (battery low, pipeline fault, lost localization); motion requests are
           refused until the condition clears

Controlling console: the first console that requests control holds it. Other consoles are observers:
their motion requests are refused with the reason, until they take control explicitly. Stop is
accepted from every console and from the server.

The arbiter has no side effects on the robot. Every call returns which owner it ended, so the caller
cancels the navigator, returns the brain to shadow mode, sends zero, and records the event.
"""
import time

OWNERS = ('idle', 'manual', 'nav', 'brain', 'retrace', 'posture', 'halt')
TASKS = ('manual', 'nav', 'brain', 'retrace', 'posture')

# (requested, current) -> the request may end the current owner
PREEMPT = {
    ('manual', 'nav'),        # operator takeover of a navigation task
    ('manual', 'brain'),      # operator takeover of brain drive
    ('retrace', 'manual'),
    ('retrace', 'nav'),
    ('retrace', 'brain'),
}


class Arbiter:
    MANUAL_IDLE_S = 1.0       # manual ownership lapses this long after the last manual input
    POSTURE_TIMEOUT_S = 10.0  # a posture transition that is never confirmed is released after this
    RETRACE_TIMEOUT_S = 370.0  # bridge bound on a return along the path (360 s) plus margin

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.owner = 'idle'
        self.since = clock()
        self.reason = 'start'
        self.controller = None          # client id holding control, or None
        self.controller_name = None
        self.halts = {}                 # latched halt reasons: key -> text
        self.cmd = (0.0, 0.0)
        self.cmd_at = -1e9
        self.last_input = -1e9
        self.reflex = False             # a brain reflex is commanding inside a nav task
        self.history = []               # last transitions, for the console and the record
        self.transitions = 0            # numbers history entries, so the server can log each one once

    # ------------------------------------------------------------------ internals
    def _set(self, owner, reason):
        if owner != self.owner:
            self.transitions += 1
            self.history = (self.history + [dict(n=self.transitions, t=time.time(), owner=owner, previous=self.owner,
                                                 reason=reason)])[-30:]
        self.owner, self.since, self.reason = owner, self.clock(), reason
        self.cmd, self.cmd_at, self.reflex = (0.0, 0.0), -1e9, False

    def _client_ok(self, client):
        """Server requests (client None) always pass; a console needs control or claims it when free."""
        if client is None or self.controller is None or self.controller == client:
            return True, None
        return False, '%s holds control; use Take control first' % (self.controller_name or self.controller)

    # ------------------------------------------------------------------ consoles
    def take_control(self, client, name=None):
        previous = self.controller_name if self.controller not in (None, client) else None
        self.controller, self.controller_name = client, name or str(client)
        ended = None
        if previous and self.owner == 'manual':
            ended = self.owner
            self._set('idle', 'control taken by %s' % self.controller_name)
        return previous, ended

    def client_lost(self, client):
        """The controlling console disconnected: manual control and brain drive end, a nav task continues."""
        if client is None or client != self.controller:
            return None
        self.controller = self.controller_name = None
        if self.owner in ('manual', 'brain'):
            ended = self.owner
            self._set('idle', 'controlling console disconnected')
            return ended
        return None

    def allowed(self, client):
        """May this console change a running task (goal, parameters, route, guard reset)? Returns (ok, why)."""
        return self._client_ok(client)

    # ------------------------------------------------------------------ tasks
    def request(self, kind, client=None, name=None, reason=''):
        """Ask for ownership. Returns (ok, why, ended_owner_or_None)."""
        assert kind in TASKS, kind
        if self.halts:
            if kind == 'posture':
                # a stand / crouch stays available during a halt (battery low: the server crouches itself);
                # the halt keeps ownership, so nothing can move meanwhile
                return True, None, None
            return False, 'motion halted: %s' % '; '.join(self.halts.values()), None
        ok, why = self._client_ok(client)
        if not ok:
            return False, why, None
        self.expire()
        current = self.owner
        if current == kind:
            if client is not None and self.controller is None:
                self.controller, self.controller_name = client, name or str(client)
            return True, None, None
        if current != 'idle' and (kind, current) not in PREEMPT:
            return False, '%s refused: %s is active (%s); stop it first' % (kind, current, self.reason), None
        if client is not None and self.controller is None:
            self.controller, self.controller_name = client, name or str(client)
        ended = None if current == 'idle' else current
        self._set(kind, reason or kind)
        return True, None, ended

    def release(self, kind, reason=''):
        """The owner finished (arrived, cancelled, confirmed). Releasing someone else's ownership is a no-op."""
        if self.owner == kind:
            self._set('idle', reason or '%s ended' % kind)
            return True
        return False

    def stop(self, reason='stop'):
        """Accepted from every console and from the server. Returns the owner it ended."""
        ended = self.owner if self.owner in TASKS else None
        if self.owner != 'halt':
            self._set('idle', reason)
        return ended

    def halt(self, key, text):
        """Latch a safety halt. Returns the owner it ended."""
        self.halts[key] = text
        ended = self.owner if self.owner in TASKS else None
        if self.owner != 'halt':
            self._set('halt', text)
        return ended

    def clear(self, key):
        if self.halts.pop(key, None) is not None and not self.halts and self.owner == 'halt':
            self._set('idle', 'halt cleared: %s' % key)

    # ------------------------------------------------------------------ commands
    def submit(self, kind, v, w, reflex=False):
        """A velocity from `kind`; ignored unless `kind` owns motion. Returns whether it was accepted."""
        if self.owner != kind or kind in ('posture', 'retrace'):
            return False
        now = self.clock()
        self.cmd, self.cmd_at, self.reflex = (float(v), float(w)), now, bool(reflex)
        if kind == 'manual':
            self.last_input = now
        return True

    def command(self, lease):
        """The velocity to send now: the owner's last command while its lease holds, else zero."""
        if self.owner not in ('manual', 'nav', 'brain'):
            return 0.0, 0.0
        if self.clock() - self.cmd_at >= lease:
            return 0.0, 0.0
        return self.cmd

    def expire(self):
        """Time-based releases. Returns the owner it ended, if any."""
        now = self.clock()
        if self.owner == 'manual' and now - max(self.last_input, self.since) > self.MANUAL_IDLE_S:
            self._set('idle', 'manual input stopped')
            return 'manual'
        if self.owner == 'posture' and now - self.since > self.POSTURE_TIMEOUT_S:
            self._set('idle', 'posture not confirmed within %.0f s' % self.POSTURE_TIMEOUT_S)
            return 'posture'
        if self.owner == 'retrace' and now - self.since > self.RETRACE_TIMEOUT_S:
            self._set('idle', 'return along the path timed out')
            return 'retrace'
        return None

    def status(self, client=None):
        return dict(owner=self.owner, reason=self.reason, since_s=round(self.clock() - self.since, 1),
                    controller=self.controller_name, you=(client is not None and client == self.controller),
                    halts=sorted(self.halts.values()), reflex=self.reflex, history=self.history[-8:])
