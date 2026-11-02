# Stage 3 protocol — closed-loop simulation, run stage3_002

Locked before execution (protocol_lock_stage3.json holds the SHA-256 of every file used).
stage3_001 (development run: scripted objects at 0.6 m/s that never stop) is kept as recorded;
it showed the escape response but no policy at 0.10 m/s reverse can avoid such an object.

Code: sim_brain.py, retina.py (LidarRetinaV3), brain.py, decoder.py, envelope.py,
config/loom_registry.json; the map package onboard_20260926_manual_cleanup_20261005.
Arms: brain (retina -> full connectome -> decoder -> envelope) and blind (constant 0.15 m/s
forward -> envelope), one seed (20261010). The blind arm is a reference, not a criterion.

| ID | Scenario | Duration | Pass criterion (brain arm) |
|---|---|---|---|
| C1 | wall_ahead | 40 s | 0 contacts; envelope overrides <= 10 % of windows; min clearance >= 0.50 m |
| C2 | roam_open | 120 s | 0 contacts; ESCAPE in <= 3 % of windows (false escapes) |
| C3 | person_front / person_left / person_right (0.5 m/s, stops at 0.7 m) | 25 s each | 0 contacts; ESCAPE or BACK_OFF within 1.0 s of loom onset (first window with loom > 0.05 rad/s); robot farther from the person 3 s after onset than at onset |

Contact = turning point closer than 0.35 m (body radius) to a wall cell or object surface.
All five C1-C3 rows must pass for stage 3 to pass. A failure is recorded, not re-run in place.

## Amendment 1 — run stage3_003 (decoder v2), locked before execution

stage3_002 result: C1 PASS, C2 PASS, C3 FAIL x3 (no contacts, fast reactions front/left, but the
robot did not end farther from the stopped person; right-side reaction 4.5 s). Kept as recorded.
Change: decoder v2 (decoder.py DecoderV2, selected with LOOM_DECODER=2): a giant-fibre burst
(DNp01 mean >= 80 Hz) starts a 1.5 s escape motor program (reverse 0.10 m/s, turn away from the
side with the stronger DNp01, up to 0.40 rad/s); otherwise decoding as v1. The envelope applies.
Criteria C1-C3 unchanged; ESCAPE_PROGRAM windows count as escapes for C2 and as reactions for C3.

## Amendment 2 — run stage3_004 (decoder v3), locked before execution

stage3_003 result: C1 PASS, C2 FAIL (escape windows 4.2 %), C3 front PASS, left/right FAIL; kept.
Cause found: the side choice was right (stronger DNp01 faces the person) but reversing while turning
away from a lateral threat swung the rear toward it. Change (decoder.py DecoderV3, LOOM_DECODER=3):
trigger = DNp01 mean over the last two windows >= 80 Hz; GF asymmetry |a| < 0.30 -> reverse
0.10 m/s straight; otherwise turn away (0.40 rad/s, sign of a) while driving forward 0.08 m/s;
1.5 s program. Criteria C1-C3 unchanged.

## Amendment 3 — run stage3_005 (decoder v4), locked before execution

stage3_004: C1 PASS, C2 PASS (2.5 %), C3 front PASS, left FAIL (1.01 -> 1.00 m), right FAIL
(reaction 4.5 s); kept. Bug: the escape trigger averaged both giant fibres; a lateral loom drives
mainly the ipsilateral one, so side threats rarely reached the threshold. Change (DecoderV4,
LOOM_DECODER=4): trigger on max(DNp01_L, DNp01_R) averaged over the last two windows >= 80 Hz;
direction choice as v3. Criteria unchanged. This is the last decoder amendment before reporting.

## Amendment 4 — run stage3_006 (decoder v5), locked before execution

Context: stage 5 (stage5_001) showed escapes on the robot that were hardly visible (turns of
12-25 deg, the forward part zeroed at the geofence). Change (DecoderV5, LOOM_DECODER=5): trigger,
side choice and timing as v4; motor program frontal reverse 0.20 m/s and lateral turn 0.80 rad/s
with 0.12 m/s forward, 2.0 s. Purpose of this run: check in simulation that the larger program
causes no contacts and no extra false escapes before it drives the robot. Criteria C1-C3 unchanged.

## Amendment 5 — run stage3_007 (decoder v6), locked before execution

Context: stage5_003 on the robot: loom -> escape decision median 0.35 s (0.09-1.08 s), 4 of 12 looms
never triggered; operator asked for faster and much more visible escapes. Change (DecoderV6,
LOOM_DECODER=6): trigger on the first window with max(DNp01_L, DNp01_R) >= 60 Hz; side choice from
that window as before; program 1.5 s, frontal reverse 0.30 m/s, lateral turn 1.0 rad/s with 0.20 m/s
forward; a burst with a different side choice restarts the program. Simulation runs the decoder
output through the envelope only (no brain_link limits). Criteria C1-C3 unchanged.

## Amendment 6 — run stage3_008 (decoder v7), locked before execution

Context: stage5_004-006 on the robot; the operator asked that the robot sometimes stop where it is,
sometimes answer a disturbance with a sustained flight, and sometimes wander. Change (DecoderV7,
LOOM_DECODER=7): REST when the smoothed DNp09 drive (1 s) < 8 Hz until > 20 Hz; a giant-fibre burst
(max DNp01 >= 60 Hz) while that drive is < 15 Hz gives FREEZE, escalating to an escape at DNp01
>= 100 Hz or after 1.5 s of continued bursts, ending after 2 s without bursts; escape programs as
v6 but the side choice is kept unless a burst is clearly lateral on the other side (|asym| >= 0.45),
frontal programs reverse 1.5 s then turn 2.5 s at 1.0 rad/s; after every program FLEE at 0.20 m/s
with DNa02 steering for 1.5 s + 2 s x arousal (cap 8 s), arousal = decoder-side leaky count of
threat onsets (tau 30 s), an engineering state, not connectome activity. Simulation runs the
decoder output through the envelope only.
Criteria for this run (stage3_eval7.py), set before execution because v7 may answer by freezing:
- C1 wall_ahead unchanged.
- C2 roam_open: 0 contacts; <= 3 defensive onsets (FREEZE or ESCAPE_PROGRAM entered) in 120 s.
  REST share and bouts, FLEE bouts reported.
- C3 person_front/left/right: 0 contacts; first FREEZE, ESCAPE_PROGRAM or BACK_OFF within 1.0 s of
  loom onset; if an escape program starts, the robot is farther from the person 3 s after its start
  than at its start. The v6 metric (distance 3 s after onset) is reported, not a criterion.

## Amendment 7 — run stage3_009 (decoder v8), locked before execution

stage3_008 kept as recorded (C2 FAIL: flee into walls -> wall looms -> new escapes and rising
arousal, a self-sustaining cascade). Change (DecoderV8, LOOM_DECODER=8), otherwise v7: a giant-fibre
burst during FLEE steers the flight away for 0.6 s (lateral: turn away at 1.0 rad/s with 0.10 m/s;
frontal: stop and turn) without starting a new program or resetting the flight timer; arousal rises
only for onsets outside ESCAPE/FLEE. Criteria as amendment 6 (stage3_eval7.py).

## Amendment 8 — run stage3_010 (decoder v9), locked before execution

Context: stage5_007 (v8) rested 48 % of the time; the model has no intrinsic walking drive.
The operator chose an explicit decoder-side endogenous exploration drive over a brain-side input.
Change (DecoderV9, LOOM_DECODER=9), otherwise v8: walk bouts 20-45 s / pauses 4-12 s from a seeded
generator (20261011); during walk bouts forward >= 0.10 m/s with DNa02 steering and neural REST
suppressed (state EXPLORE, neural_v logged); flights 6 s + 4 s x arousal, cap 20 s. Criteria as
amendment 6 (stage3_eval7.py); EXPLORE share reported.
