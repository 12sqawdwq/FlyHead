"""Descending-neuron rates -> bounded motor intent. Fixed formulas; no hidden constant drive.

Calibrated on stage 1 (runs/stage1_001):
  forward   <- DNp09 (P9) mean; 60 Hz at LC9 120 Hz
  backward  <- MDN mean; 26-39 Hz under frontal loom
  turning   <- DNa02 right - left (DNa01 is biased by the forward drive; diagnostic only)
  escape    <- giant fibre DNp01 mean (state flag: forward is withheld while it fires)
Yaw sign (literature, to be verified in stage 3): DNa02 on one side turns the fly toward that
side, so DNa02_right > DNa02_left -> turn right -> robot yaw rate negative (ROS: + = left).
Speeds are caps for the shadow intent; the host safety envelope can only reduce them.
"""
import math

P9_REF_HZ = 60.0
MDN_REF_HZ = 35.0
DNA02_REF_HZ = 20.0
GF_ESCAPE_HZ = 80.0
MAX_FORWARD = 0.15                  # m/s, stage-5 start cap
MAX_BACKWARD = 0.10
MAX_YAW = 0.40                      # rad/s
YAW_SIGN_RIGHT_DNA02 = -1.0         # DNa02_right dominant -> negative (clockwise) robot yaw


def clip01(x):
    return max(0.0, min(1.0, x))


def decode(rates):
    """rates: {(type, side): Hz}. Returns a shadow intent dict."""
    r = lambda t, s: rates.get((t, s), 0.0)
    p9 = (r('DNp09', 'left') + r('DNp09', 'right')) / 2
    mdn = (r('MDN', 'left') + r('MDN', 'right')) / 2
    gf = (r('DNp01', 'left') + r('DNp01', 'right')) / 2
    turn = r('DNa02', 'right') - r('DNa02', 'left')
    escape = gf >= GF_ESCAPE_HZ
    forward = 0.0 if escape else clip01(p9 / P9_REF_HZ) * MAX_FORWARD
    backward = clip01(mdn / MDN_REF_HZ) * MAX_BACKWARD
    v = forward - backward
    yaw = YAW_SIGN_RIGHT_DNA02 * max(-1.0, min(1.0, turn / DNA02_REF_HZ)) * MAX_YAW
    if escape:
        state = 'ESCAPE'
    elif v < -0.01:
        state = 'BACK_OFF'
    elif abs(yaw) > 0.05:
        state = 'TURN_LEFT' if yaw > 0 else 'TURN_RIGHT'
    elif v > 0.01:
        state = 'FORWARD'
    else:
        state = 'HOLD'
    return dict(state=state, v=round(v, 4), w=round(yaw, 4), p9_hz=round(p9, 1), mdn_hz=round(mdn, 1),
                gf_hz=round(gf, 1), dna02_r_minus_l_hz=round(turn, 1))


# ---------------------------------------------------------------------------------------------
# Decoder v2 (2026-10-10, amendment after stage3_002 failed C3): the GF-driven escape lasted only
# 2-8 windows, so the robot backed up < 1 s and the forward drive took it back toward a stopped
# person. In the fly a giant-fibre spike triggers a ballistic takeoff that runs to completion;
# v2 maps a GF burst to a fixed escape motor program. The brain still decides WHEN (GF burst) and
# WHICH WAY (GF left/right asymmetry: the stronger side faces the loom, the robot turns away).
ESCAPE_PROGRAM_S = 1.5
ESCAPE_BACK = 0.10                  # m/s during the program
ESCAPE_TURN_MAX = 0.40              # rad/s
GF_ASYM_REF_HZ = 50.0               # stage 1: left loom 200 Hz -> GF L 134-185 vs R 49-115 Hz


class DecoderV2:
    VERSION = 2

    def __init__(self):
        self.program_until = -1.0
        self.program_w = 0.0

    def decode(self, rates, t):
        base = decode(rates)
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        if base['state'] == 'ESCAPE':
            asym = (gf_l - gf_r) / GF_ASYM_REF_HZ          # > 0: loom on the left -> turn right (w < 0)
            self.program_w = -max(-1.0, min(1.0, asym)) * ESCAPE_TURN_MAX
            self.program_until = t + ESCAPE_PROGRAM_S
        if t < self.program_until:
            return dict(base, state='ESCAPE_PROGRAM', v=-ESCAPE_BACK, w=round(self.program_w, 4),
                        program_left_s=round(self.program_until - t, 2), gf_left_hz=gf_l, gf_right_hz=gf_r,
                        decoder_version=2)
        return dict(base, decoder_version=2)


# ---------------------------------------------------------------------------------------------
# Decoder v3 (2026-10-10, amendment 2 after stage3_003: C2 4.2 % > 3 %, C3 left/right FAIL).
# stage3_003 showed the brain's side choice was right (left person -> DNp01 left > right -> turn
# right) but reversing during a turn away from a LATERAL threat swings the rear toward it
# (person bearing +77 deg -> +150 deg, distance 0.91 -> 0.67 m). v3: the escape direction follows
# the GF asymmetry a = (L - R) / (L + R): |a| < LATERAL_ASYM -> frontal threat: reverse straight;
# otherwise lateral: turn away (sign of a) and drive forward. Trigger: GF mean over the last two
# windows >= GF_ESCAPE_HZ (single-window bursts caused the false escapes in roam_open).
LATERAL_ASYM = 0.30
ESCAPE_FWD = 0.08                   # m/s forward while turning away from a lateral threat


class DecoderV3:
    VERSION = 3

    def __init__(self):
        self.program_until = -1.0
        self.program = (0.0, 0.0)
        self.gf_hist = []

    def decode(self, rates, t):
        base = decode(rates)
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        self.gf_hist = (self.gf_hist + [(gf_l, gf_r)])[-2:]
        mean_gf = sum((a + b) / 2 for a, b in self.gf_hist) / len(self.gf_hist)
        if len(self.gf_hist) == 2 and mean_gf >= GF_ESCAPE_HZ and t >= self.program_until:
            sl = sum(a for a, _ in self.gf_hist); sr = sum(b for _, b in self.gf_hist)
            asym = (sl - sr) / max(1e-6, sl + sr)
            if abs(asym) < LATERAL_ASYM:
                self.program = (-ESCAPE_BACK, 0.0)                         # frontal: back straight away
            else:
                self.program = (ESCAPE_FWD, -math.copysign(ESCAPE_TURN_MAX, asym))   # lateral: turn away, go
            self.program_until = t + ESCAPE_PROGRAM_S
            self.program_asym = asym
        if t < self.program_until:
            return dict(base, state='ESCAPE_PROGRAM', v=self.program[0], w=self.program[1],
                        program_left_s=round(self.program_until - t, 2), gf_asym=round(self.program_asym, 2),
                        decoder_version=3)
        if base['state'] == 'ESCAPE':           # GF high but not (yet) a two-window burst: hold forward
            return dict(base, v=min(base['v'], 0.0), decoder_version=3)
        return dict(base, decoder_version=3)


# ---------------------------------------------------------------------------------------------
# Decoder v4 (2026-10-10, amendment 3 after stage3_004: C3 left 1.01 -> 1.00 m, right reaction
# 4.5 s). Bug: the trigger averaged both giant fibres, but a lateral loom drives mainly the
# ipsilateral one (right 100 Hz, left 0 -> mean 50 < 80), so side threats were under-detected.
# v4 triggers on the stronger side: max(DNp01_L, DNp01_R) averaged over the last two windows.
class DecoderV4(DecoderV3):
    VERSION = 4

    def decode(self, rates, t):
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        hist = (self.gf_hist + [(gf_l, gf_r)])[-2:]
        strong = sum(max(a, b) for a, b in hist) / len(hist)
        if len(hist) == 2 and strong >= GF_ESCAPE_HZ and t >= self.program_until:
            # present the burst to the v3 logic as a symmetric mean that clears the threshold,
            # keeping v3's asymmetry-based direction choice unchanged
            self.gf_hist = hist
            sl = sum(a for a, _ in hist); sr = sum(b for _, b in hist)
            asym = (sl - sr) / max(1e-6, sl + sr)
            self.program = (-ESCAPE_BACK, 0.0) if abs(asym) < LATERAL_ASYM else (ESCAPE_FWD, -math.copysign(ESCAPE_TURN_MAX, asym))
            self.program_until = t + ESCAPE_PROGRAM_S
            self.program_asym = asym
        else:
            self.gf_hist = hist
        base = decode(rates)
        if t < self.program_until:
            return dict(base, state='ESCAPE_PROGRAM', v=self.program[0], w=self.program[1],
                        program_left_s=round(self.program_until - t, 2), gf_asym=round(self.program_asym, 2), decoder_version=4)
        if base['state'] == 'ESCAPE':
            return dict(base, v=min(base['v'], 0.0), decoder_version=4)
        return dict(base, decoder_version=4)


# ---------------------------------------------------------------------------------------------
# Decoder v5 (2026-10-10, stage 5 amendment 2 after stage5_001: escapes on the robot were hardly
# visible). Trigger, side choice and timing as v4 (the brain still decides when and which way);
# only the motor program is larger: frontal reverse 0.20 m/s for 2.0 s (0.40 m), lateral turn
# away 0.80 rad/s with 0.12 m/s forward for 2.0 s (about 90 deg).
class DecoderV5(DecoderV3):
    VERSION = 5
    PROGRAM_S, BACK, FWD, TURN = 2.0, 0.20, 0.12, 0.80

    def decode(self, rates, t):
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        hist = (self.gf_hist + [(gf_l, gf_r)])[-2:]
        self.gf_hist = hist
        strong = sum(max(a, b) for a, b in hist) / len(hist)
        if len(hist) == 2 and strong >= GF_ESCAPE_HZ and t >= self.program_until:
            sl = sum(a for a, _ in hist); sr = sum(b for _, b in hist)
            asym = (sl - sr) / max(1e-6, sl + sr)
            self.program = (-self.BACK, 0.0) if abs(asym) < LATERAL_ASYM else (self.FWD, -math.copysign(self.TURN, asym))
            self.program_until = t + self.PROGRAM_S
            self.program_asym = asym
        base = decode(rates)
        if t < self.program_until:
            return dict(base, state='ESCAPE_PROGRAM', v=self.program[0], w=self.program[1],
                        program_left_s=round(self.program_until - t, 2), gf_asym=round(self.program_asym, 2), decoder_version=5)
        if base['state'] == 'ESCAPE':
            return dict(base, v=min(base['v'], 0.0), decoder_version=5)
        return dict(base, decoder_version=5)


# ---------------------------------------------------------------------------------------------
# Decoder v6 (2026-10-10, stage 5 amendment 2 after stage5_003: operator asked for faster, much
# more visible escapes). Measured on the robot: loom -> escape decision took a median 0.35 s (up to
# 1.1 s, 4 of 12 looms never triggered) because v4/v5 wait for two windows averaging >= 80 Hz.
# v6: the escape fires on the first window with the stronger giant fibre >= GF_ESCAPE_V6_HZ; side
# choice from that window's asymmetry as before. Motor program at the robot's limits for 1.5 s:
# frontal reverse 0.30 m/s; lateral turn away 1.0 rad/s with 0.20 m/s forward. A burst whose side
# choice differs from the running program (other side, or frontal vs lateral) restarts it, so a
# threat that switches side is followed at once.
GF_ESCAPE_V6_HZ = 60.0


class DecoderV6(DecoderV3):
    VERSION = 6
    PROGRAM_S, BACK, FWD, TURN = 1.5, 0.30, 0.20, 1.0

    def choose(self, gf_l, gf_r):
        asym = (gf_l - gf_r) / max(1e-6, gf_l + gf_r)
        program = (-self.BACK, 0.0) if abs(asym) < LATERAL_ASYM else (self.FWD, -math.copysign(self.TURN, asym))
        return program, asym

    def decode(self, rates, t):
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        if max(gf_l, gf_r) >= GF_ESCAPE_V6_HZ:
            program, asym = self.choose(gf_l, gf_r)
            if t >= self.program_until or program != self.program:
                self.program, self.program_asym, self.program_until = program, asym, t + self.PROGRAM_S
        base = decode(rates)
        if t < self.program_until:
            return dict(base, state='ESCAPE_PROGRAM', v=self.program[0], w=self.program[1],
                        program_left_s=round(self.program_until - t, 2), gf_asym=round(self.program_asym, 2), decoder_version=6)
        if base['state'] == 'ESCAPE':
            return dict(base, v=min(base['v'], 0.0), decoder_version=6)
        return dict(base, decoder_version=6)


# ---------------------------------------------------------------------------------------------
# Decoder v7 (2026-10-11, after stage5_004-006). Three behaviours, all selected by the brain's own
# readouts, no random draws:
#   REST    the walking drive (DNp09, smoothed over P9_TAU_S) falls below REST_ENTER_HZ; the robot
#           stops where it is until the drive rises above REST_EXIT_HZ (hysteresis). Offline on
#           stage5_006 windows 8 / 20 Hz gave 14 rests, median 7 s, 30 % of the time.
#   FREEZE  a giant-fibre burst while the walking drive is low (< FREEZE_BELOW_HZ): the robot
#           stops. It escalates to an escape if the giant fibre reaches GF_FLEE_HZ or the threat
#           keeps firing FREEZE_ESCALATE_S; it ends after FREEZE_CLEAR_S without giant-fibre activity.
#   ESCAPE  as v6, plus: frontal threats reverse, then turn away (TURN_AROUND_S); the side choice is
#           kept for the whole program and changes only on a clear lateral burst on the other side
#           (|asym| >= CLEAR_SIDE) -- the v6 frontal/lateral flip cut reverses to 0.1-0.6 s.
#   FLEE    after the program the robot keeps running (FLEE_V, steering from DNa02) for
#           FLEE_BASE_S + FLEE_PER_AROUSAL_S * arousal (cap FLEE_MAX_S).
# Behavioural basis (from the literature, to be checked before citing): walking flies answer a
# looming stimulus by freezing or fleeing depending on their own walking speed at the time, and
# repeated threats leave a persistent, decaying state of faster running. The arousal variable is a
# decoder-side leaky integrator of threat onsets (tau AROUSAL_TAU_S) -- an engineering model of that
# persistent state, NOT activity of the simulated connectome.
GF_FLEE_HZ = 100.0


class DecoderV7(DecoderV6):
    VERSION = 7
    CLEAR_SIDE = 0.45
    P9_TAU_S, REST_ENTER_HZ, REST_EXIT_HZ = 1.0, 8.0, 20.0
    FREEZE_BELOW_HZ, FREEZE_ESCALATE_S, FREEZE_CLEAR_S, GF_QUIET_HZ = 15.0, 1.5, 2.0, 30.0
    TURN_AROUND_S = 2.5
    AROUSAL_TAU_S, ONSET_GAP_S = 30.0, 1.0
    FLEE_V, FLEE_BASE_S, FLEE_PER_AROUSAL_S, FLEE_MAX_S = 0.20, 1.5, 2.0, 8.0

    def __init__(self):
        super().__init__()
        self.t_last = None
        self.p9_s = None
        self.arousal = 0.0
        self.last_burst_t = -1e9
        self.mode = None                # None (wander) | 'rest' | 'freeze' | 'escape' | 'flee'
        self.phase = None               # escape: 'reverse' | 'turn' | 'lateral'
        self.until = -1.0
        self.since = 0.0
        self.program_asym = 0.0

    def _escape(self, asym, t):
        self.mode, self.since, self.program_asym = 'escape', t, asym
        if abs(asym) < LATERAL_ASYM:
            self.phase, self.program = 'reverse', (-self.BACK, 0.0)
        else:
            self.phase, self.program = 'lateral', (self.FWD, -math.copysign(self.TURN, asym))
        self.until = t + self.PROGRAM_S

    def _clear_switch(self, asym):
        if abs(asym) < max(LATERAL_ASYM, self.CLEAR_SIDE):
            return False                                    # frontal or ambiguous: keep the program
        if self.phase == 'reverse':
            return True                                     # threat now clearly on one side
        return self.phase in ('lateral', 'turn') and math.copysign(1, asym) != math.copysign(1, self.program_asym)

    def decode(self, rates, t):
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        gf_max = max(gf_l, gf_r)
        base = decode(rates)
        dt = 0.0 if self.t_last is None else max(0.0, t - self.t_last)
        self.t_last = t
        self.arousal *= math.exp(-dt / self.AROUSAL_TAU_S)
        p9 = base['p9_hz']
        self.p9_s = p9 if self.p9_s is None else self.p9_s + (p9 - self.p9_s) * min(1.0, dt / self.P9_TAU_S)
        burst = gf_max >= GF_ESCAPE_V6_HZ
        if burst and t - self.last_burst_t > self.ONSET_GAP_S:
            self.arousal += 1.0
        if burst:
            self.last_burst_t = t
        _, asym = self.choose(gf_l, gf_r)

        if burst:
            if self.mode in (None, 'rest'):
                if self.p9_s < self.FREEZE_BELOW_HZ and gf_max < GF_FLEE_HZ:
                    self.mode, self.since = 'freeze', t
                else:
                    self._escape(asym, t)
            elif self.mode == 'freeze':
                if gf_max >= GF_FLEE_HZ or t - self.since >= self.FREEZE_ESCALATE_S:
                    self._escape(asym, t)
            elif self.mode == 'flee':
                self._escape(asym, t)
            elif self.mode == 'escape':
                if self._clear_switch(asym):
                    self._escape(asym, t)
                elif self.phase in ('reverse', 'lateral'):
                    self.until = max(self.until, t + self.PROGRAM_S)      # same threat: keep going

        # phase transitions
        if self.mode == 'escape' and t >= self.until:
            if self.phase == 'reverse':
                self.phase, self.program = 'turn', (0.0, -math.copysign(self.TURN, self.program_asym or 1e-9))
                self.until = t + self.TURN_AROUND_S
            else:
                self.mode, self.phase = 'flee', None
                self.until = t + min(self.FLEE_MAX_S, self.FLEE_BASE_S + self.FLEE_PER_AROUSAL_S * self.arousal)
        if self.mode == 'flee' and t >= self.until:
            self.mode = None
        if self.mode == 'freeze' and gf_max < self.GF_QUIET_HZ and t - self.last_burst_t >= self.FREEZE_CLEAR_S:
            self.mode = None
        if self.mode is None and self.p9_s < self.REST_ENTER_HZ:
            self.mode = 'rest'
        elif self.mode == 'rest' and self.p9_s > self.REST_EXIT_HZ:
            self.mode = None

        extra = dict(p9_smooth_hz=round(self.p9_s, 1), arousal=round(self.arousal, 2), decoder_version=7)
        if self.mode == 'escape':
            return dict(base, state='ESCAPE_PROGRAM', phase=self.phase, v=self.program[0], w=self.program[1],
                        program_left_s=round(self.until - t, 2), gf_asym=round(self.program_asym, 2), **extra)
        if self.mode == 'flee':
            return dict(base, state='FLEE', v=self.FLEE_V, w=base['w'], flee_left_s=round(self.until - t, 2), **extra)
        if self.mode in ('freeze', 'rest'):
            return dict(base, state=self.mode.upper(), v=0.0, w=0.0, **extra)
        if base['state'] == 'ESCAPE':
            return dict(base, v=min(base['v'], 0.0), **extra)
        return dict(base, **extra)


# ---------------------------------------------------------------------------------------------
# Decoder v8 (2026-10-11, amendment 7 after stage3_008 C2: 8 defensive onsets in roam_open). In v7
# the flight itself made the walls loom: every burst during FLEE started a new escape + flee and
# raised arousal, so flights grew (cascade). v8, otherwise as v7:
#   - a burst during FLEE steers the flight away for STEER_S (lateral: turn away at TURN with half
#     flight speed; frontal: stop and turn) without restarting the program or the flight timer;
#   - arousal rises only for threat onsets outside ESCAPE/FLEE (looming caused by the robot's own
#     flight is not counted as a new threat).
class DecoderV8(DecoderV7):
    VERSION = 8
    STEER_S = 0.6

    def __init__(self):
        super().__init__()
        self.steer_until = -1.0
        self.steer = (0.0, 0.0)

    def decode(self, rates, t):
        r = lambda ty, s: rates.get((ty, s), 0.0)
        gf_l, gf_r = r('DNp01', 'left'), r('DNp01', 'right')
        gf_max = max(gf_l, gf_r)
        base = decode(rates)
        dt = 0.0 if self.t_last is None else max(0.0, t - self.t_last)
        self.t_last = t
        self.arousal *= math.exp(-dt / self.AROUSAL_TAU_S)
        p9 = base['p9_hz']
        self.p9_s = p9 if self.p9_s is None else self.p9_s + (p9 - self.p9_s) * min(1.0, dt / self.P9_TAU_S)
        burst = gf_max >= GF_ESCAPE_V6_HZ
        if burst and t - self.last_burst_t > self.ONSET_GAP_S and self.mode not in ('escape', 'flee'):
            self.arousal += 1.0
        if burst:
            self.last_burst_t = t
        _, asym = self.choose(gf_l, gf_r)

        if burst:
            if self.mode in (None, 'rest'):
                if self.p9_s < self.FREEZE_BELOW_HZ and gf_max < GF_FLEE_HZ:
                    self.mode, self.since = 'freeze', t
                else:
                    self._escape(asym, t)
            elif self.mode == 'freeze':
                if gf_max >= GF_FLEE_HZ or t - self.since >= self.FREEZE_ESCALATE_S:
                    self._escape(asym, t)
            elif self.mode == 'flee':
                turn = -math.copysign(self.TURN, asym or 1e-9)
                self.steer = (0.0, turn) if abs(asym) < LATERAL_ASYM else (self.FLEE_V / 2, turn)
                self.steer_until = t + self.STEER_S
            elif self.mode == 'escape':
                if self._clear_switch(asym):
                    self._escape(asym, t)
                elif self.phase in ('reverse', 'lateral'):
                    self.until = max(self.until, t + self.PROGRAM_S)

        if self.mode == 'escape' and t >= self.until:
            if self.phase == 'reverse':
                self.phase, self.program = 'turn', (0.0, -math.copysign(self.TURN, self.program_asym or 1e-9))
                self.until = t + self.TURN_AROUND_S
            else:
                self.mode, self.phase = 'flee', None
                self.until = t + min(self.FLEE_MAX_S, self.FLEE_BASE_S + self.FLEE_PER_AROUSAL_S * self.arousal)
        if self.mode == 'flee' and t >= self.until:
            self.mode = None
        if self.mode == 'freeze' and gf_max < self.GF_QUIET_HZ and t - self.last_burst_t >= self.FREEZE_CLEAR_S:
            self.mode = None
        if self.mode is None and self.p9_s < self.REST_ENTER_HZ:
            self.mode = 'rest'
        elif self.mode == 'rest' and self.p9_s > self.REST_EXIT_HZ:
            self.mode = None

        extra = dict(p9_smooth_hz=round(self.p9_s, 1), arousal=round(self.arousal, 2), decoder_version=8)
        if self.mode == 'escape':
            return dict(base, state='ESCAPE_PROGRAM', phase=self.phase, v=self.program[0], w=self.program[1],
                        program_left_s=round(self.until - t, 2), gf_asym=round(self.program_asym, 2), **extra)
        if self.mode == 'flee':
            if t < self.steer_until:
                return dict(base, state='FLEE', phase='steer', v=self.steer[0], w=self.steer[1],
                            flee_left_s=round(self.until - t, 2), **extra)
            return dict(base, state='FLEE', v=self.FLEE_V, w=base['w'], flee_left_s=round(self.until - t, 2), **extra)
        if self.mode in ('freeze', 'rest'):
            return dict(base, state=self.mode.upper(), v=0.0, w=0.0, **extra)
        if base['state'] == 'ESCAPE':
            return dict(base, v=min(base['v'], 0.0), **extra)
        return dict(base, **extra)


# ---------------------------------------------------------------------------------------------
# Decoder v9 (2026-10-11, stage 5 amendment 5 after stage5_007; operator: more spontaneous roaming,
# and after a disturbance move away fast to a distant place). stage5_007 showed the simulated
# connectome has no intrinsic walking drive: DNp09 is ~30 Hz while the robot walks forward and
# ~10 Hz when it stands (turning in place does not restart it), so REST took 48 % of the run.
# ENGINEERING ADDITION, chosen by the operator over a brain-side background input: an endogenous
# exploration drive in the decoder (not connectome activity). It alternates walk bouts (WALK_S) and
# pauses (PAUSE_S), lengths drawn from a seeded generator (SEED, reproducible). During a walk bout
# the robot moves forward at least ENDO_V with steering from DNa02, and neural REST is suppressed;
# during a pause the neural behaviour of v8 applies unchanged (it rests if DNp09 is low). Freeze,
# escape, flight and neural BACK_OFF always take precedence. Records carry state 'EXPLORE' and
# neural_v whenever the endogenous drive raised the command, so neural and endogenous motion stay
# separable. Flights are longer: 6 s + 4 s x arousal, up to 20 s.
import random  # noqa: E402


class DecoderV9(DecoderV8):
    VERSION = 9
    ENDO_V = 0.10
    WALK_S, PAUSE_S, SEED = (20.0, 45.0), (4.0, 12.0), 20261011
    FLEE_BASE_S, FLEE_PER_AROUSAL_S, FLEE_MAX_S = 6.0, 4.0, 20.0

    def __init__(self):
        super().__init__()
        self.rng = random.Random(self.SEED)
        self.endo_walk = True
        self.endo_until = None

    def decode(self, rates, t):
        if self.endo_until is None:
            self.endo_until = t + self.rng.uniform(*self.WALK_S)
        elif t >= self.endo_until:
            self.endo_walk = not self.endo_walk
            self.endo_until = t + self.rng.uniform(*(self.WALK_S if self.endo_walk else self.PAUSE_S))
        out = super().decode(rates, t)
        out.update(decoder_version=9, endo_walk=self.endo_walk, endo_left_s=round(self.endo_until - t, 1))
        if not self.endo_walk or out['state'] in ('ESCAPE_PROGRAM', 'FLEE', 'FREEZE', 'BACK_OFF', 'ESCAPE'):
            return out
        if self.mode == 'rest':
            self.mode = None                      # the walk bout overrides a neural rest
        base = decode(rates)
        if base['v'] >= self.ENDO_V:
            return dict(out, state=base['state'], v=base['v'], w=base['w'])
        return dict(out, state='EXPLORE', v=self.ENDO_V, w=base['w'], neural_v=base['v'])


DECODERS = {2: DecoderV2, 3: DecoderV3, 4: DecoderV4, 5: DecoderV5, 6: DecoderV6, 7: DecoderV7, 8: DecoderV8, 9: DecoderV9}


def make_decoder(version):
    """Stateful decoder by version number; None for version 1 (the stateless decode())."""
    version = int(version or 1)
    if version == 1:
        return None
    if version not in DECODERS:
        raise ValueError('unknown decoder version %r' % version)
    return DECODERS[version]()
