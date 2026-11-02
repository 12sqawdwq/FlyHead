# loom_005 results — stages 0-3

Date: 2026-10-10. Server copies: <SERVER_ROOT>/inference_service/mappings/loom_005/.
Nothing in stages 0-3 moved the robot; all simulation and replay is offline.

## Stage 0 — contracts (PASS)
config/loom_registry.json (SHA 8b6cc094...): exact cell_type -> root_id -> model_index, annotation
SHA 9a4f8b2f... and completeness SHA 52b0ac60... checked. Inputs LC4 104, LPLC2 210, LC9 179;
readouts DNp01/02/04/06/11, DNp09, DNa01, DNa02 (2 each), MDN 4. Field side -> anatomical eye and
robot yaw sign are separate, uncalibrated tables.

## Stage 1 — dose response (runs/stage1_001)
Loom on one side -> ipsilateral giant fibre DNp01 134-185 Hz and DNp02/04/11, contralateral DNa02
10-37 Hz (turn away). Loom on both sides -> DNp01 ~200 Hz, MDN 26-39 Hz, P9 ~0 (stop, back up).
LC9 120 Hz -> P9 44-60 Hz. Compute: 109 ms p50 / 122 ms p95 per 100 ms window on the shared GPU
(another project at 99 % utilisation): ~0.9x real time. Budget not met; windows are timestamped.

## Stage 2 — offline replay (Turbo lap 2026-10-09 16:30, 420 s)
- stage2_001, retina v1: FAIL. LC4 at ceiling 26 %; loom in 75 % of still windows -> ESCAPE 33 %.
- stage2_002, retina v3 (pooled world points, world-direction bins, approach + deadband 0.12,
  stale scan -> no input): PASS. Ceiling 0.1-0.2 %; ESCAPE while still 2 %; approaching: ESCAPE 34 %,
  turn 26 %; one-sided loom -> turn away 77 % (62 windows); stale -> HOLD 92 %.

## Stage 3 — closed-loop simulation (PROTOCOL_STAGE3.md, locked per run)
| Run | Decoder | C1 wall | C2 roam | C3 front | C3 left | C3 right |
|---|---|---|---|---|---|---|
| stage3_002 | v1 | PASS | PASS (0.8 %) | FAIL 0.95->0.88 | FAIL 1.01->0.89 | FAIL (4.5 s) |
| stage3_003 | v2 escape program | PASS | FAIL (4.2 %) | PASS 0.95->1.01 | FAIL 1.01->0.85 | FAIL |
| stage3_004 | v3 frontal/lateral | PASS | PASS (2.5 %) | PASS 0.95->1.13 | FAIL 1.01->1.00 | FAIL |
| stage3_005 | v4 stronger-side trigger | PASS | PASS (2.7 %) | PASS 0.95->1.13 | FAIL 1.01->1.00 | FAIL 2.10->0.94 |

Stage 3 has NOT passed. Across all runs: 0 contacts in every brain run; the wall run stops by itself
0.89 m short with 0 % envelope overrides (blind: 65 %); real looms get a reaction 0.1-0.4 s after
they start. Side escapes turn away but do not gain distance within 3 s. The person_right row is
also affected by an evaluation flaw: its "loom onset" is a small own-motion loom at 1.3 s while the
person is still 2.1 m away, so both its latency and its distance baseline are measured from the
wrong moment. Per protocol these are recorded failures; no run was repeated in place.

## Stage 4 — shadow on the real robot (PROTOCOL_STAGE4.md; chassis locked, no brain command sent)
- stage4_001: FAULT, kept as recorded. brain_link.command() unpacked an unset geofence in shadow
  mode and stopped the server control loop at 21:03:34. Exploratory segment E1 (313 s free-form
  disturbances, brain-service log only): reactions 0.25/0.34 s; escape direction locked for 1.5 s
  even when the threat switched side (0.7-1.0 s toward the new threat); 34 s of chained escapes
  while people stayed close; open-space turn jitter in 7 % of windows (left 2:1).
- stage4_002 (amendment 1: fence skipped when unset, brain errors caught in the control loop): PASS
  with one deviation. Operator order (facing the robot's front): 3 from the operator's right
  (= robot left), 3 from the operator's left (= robot right), then front.
  | Direction | Retina side | Reaction (s) | Escape |
  |---|---|---|---|
  | robot left x3 | left, left, left | 0.3, 0.3, 0.24 | reverse straight, turn right, turn right |
  | robot right x3 | right x3 | 0.24, 0.33, 0.08 | turn left x3 |
  | front x3 | both (forward drive LC9 -> 0) | 0.23, 0.0, 0.31 | reverse straight x3 |
  First two left approaches fall in one detected episode (gap < 3 s); split by hand from the timeline.
  Side mapping: no left/right swap anywhere in LiDAR -> body frame -> retina -> brain -> decoder.
  M1: brain 84 ms/window, input age 0.18/0.29 s, stale 3.5 %. M4: 890 control cycles in shadow,
  0 non-zero commands. M3: 0 % escapes in the 24 s still segment after the trials (deviation:
  protocol asked 60 s) and 0 % in the 194 s before the trials. Would-be drive: 12 % of commands
  withheld by the localization fitness gate (0.64-0.79 with people close); envelope reduced 16 %.
- Brain windows run back to back (84 ms for 100 ms of model time): brain time ~1.2x real time.

## Stage 5 — brain drive on the robot (PROTOCOL_STAGE5.md)
- stage5_001 (decoder v4): 0 contacts, 0 RC takeovers. Deviation: crouched throughout (idle auto-
  crouch 16 s before drive). D1 120 s: drove ~2.1 m straight ahead with small right turns, slowing
  by itself as free space ahead fell (LC9 120 -> 33 Hz); envelope 0 interventions before the fence;
  reached the 2 m fence after ~65 s and then mostly sat there (the brain keeps choosing forward,
  outward). 15 cycles withheld at fitness 0.78. Six escape programs (one D1 approach, the rest
  operator approaches), all at the fence: forward part zeroed, executed in-place turns 12-25 deg in
  the right direction. Operator: escapes visible but not pronounced; the robot did not stand.
- stage5_002 (amendment 1: decoder v5, escape limits 0.20 m/s back / 0.80 rad/s, fence +0.5 m for
  escapes, 300 s idle crouch in drive; fence 1.5 m because the start point was 0.57 m off the
  cleared centre): 0 contacts. Standing in every drive record (3179/3179 with pose). D1: straight
  ahead to the fence within ~30 s, sat there until an escape turned it; ~1.1 m back inward. Max
  distance from the fence centre 2.13 m (2.0 allowed during escapes; 0.13 m coast).
  Lateral escapes: 13 programs, every one turned away from the stronger giant fibre; executed
  58-94 deg turns with 0.13-0.49 m travel (stage5_001: 12-25 deg, ~0 m).
  Frontal escapes: 4 programs (|asym| < 0.30) commanded 0.20 m/s reverse, but a person close in
  front drops localization fitness to 0.58-0.77 and the 0.80 gate withheld most cycles; executed
  reverse only a few cm. The collision envelope uses the live scan (body frame), not the pose;
  the pose is needed only for the geofence.
- stage5_003 (repeat of stage5_002): loom -> escape decision median 0.35 s (0.09-1.08 s), 4 of 12
  loom episodes never triggered; decision -> executed command +0.05-0.1 s; fitness gate delayed one
  program by 0.9 s. Ended for the operator's request for faster, stronger escapes.

## Stage 3 re-checks for stage 5 changes
- stage3_006 (decoder v5): 0 contacts; C1, C2 (1.7 %), C3 front 0.95 -> 1.46 m, C3 left 1.01 -> 1.19 m
  PASS; C3 right FAIL (known evaluation flaw: onset from own-motion loom at 2.1 m).
- stage3_007 (decoder v6: one-window trigger >= 60 Hz, reverse 0.30 m/s, turn 1.0 rad/s + 0.20 m/s,
  side switch restarts the program): 0 contacts, min clearance >= 0.55 m everywhere; C1 PASS,
  C2 PASS (2.7 %), C3 front 0.1 s, 0.95 -> 1.48 m, C3 left 0.2 s, 1.01 -> 1.06 m; C3 right FAIL (same flaw).
- stage5_004 (amendment 2: decoder v6, escape limits 0.20 / -0.30 m/s, 1.0 rad/s, escape fitness gate
  0.50): 262 s drive, standing throughout, 0 contacts reported, max 2.17 m from the fence centre.
  30 escape programs (15 frontal, 15 lateral), none withheld. Lateral: turns up to 103 deg, 0.04-0.29 m.
  Frontal: reverse executed at the full -0.30 m/s, but most bouts lasted 1-6 cycles (0.1-0.6 s):
  when the giant-fibre asymmetry hovers near 0.30 the v6 restart rule flips the program between
  frontal and lateral, so the robot moved back only 0-0.2 m. Next fix (not yet made): hysteresis on
  the frontal/lateral choice, restart only on a clear side change.
  Session ended by the operator: robot returned to 0.6 m from the charger, crouched, chassis off,
  brain service stopped, server back under the charging lock.
- stage5_005 (repeat of stage5_004, v6): drive 3993 s (operator finished after ~67 min), standing
  throughout, contacts: not yet reported by the operator. Approaches at 180-333 s: 59 escape programs
  (frontal 33, lateral 26), none withheld; frontal moved back up to 0.77 m (several 0.2-0.5 m, better
  than stage5_004's 0-0.2 m), lateral turns up to 95 deg; flip-flop between frontal/lateral still seen.
  Safety finding: the robot spent ~86% of cycles at the fence with v zeroed ('geofence'), yet its
  distance from the fence centre crept from 2.0 m to 3.43 m (1087-2622 s) and to 2.64 m (3471-3954 s)
  with near-zero executed v (only w commands passing, fitness ~0.99). Standing in-place turns appear to
  displace the robot; the fence limits v only and does not hold position. Cause not verified.
- stage5_006 (amendment 3: whole-map keep-in, 166.6 m2; turns outside restricted): 1207 s drive, ended
  by the 20 min budget (battery 46 -> 33 %). Contacts: 0 (operator report). Path 89 m, 18.5 m2 visited
  (0.5 m cells), x -7.3..3.5, y 2.0..7.5; moving 51 % of localized cycles, at the keep-in edge 47 %.
  Criterion failed: the robot reached 0.46 m outside the keep-in (limit 0.40); the hard stop fired
  (238 cycles) but the body was already past it (standing stopping lag / creep). Last ~4.5 min
  (from ~950 s) frozen at about (1.3, 7.5): localization fitness < 0.80 there (3819 cycles withheld),
  so the fitness gate stopped all motion as designed. 100 escape programs (48 frontal, max back 0.23 m;
  44 lateral, max 99 deg, 15 >= 45 deg), none withheld. Exploration still ends against edges; no
  planner was added.
- stage3_008 (amendment 6, decoder v7: REST / FREEZE / escape with side hysteresis / FLEE with
  arousal): FAILED. C1 PASS (0 overrides, min 0.89 m). C2 FAIL: 8 defensive onsets in 120 s (limit 3),
  0 contacts. Cause: the first false escape (67.9 s, a wall, same as v6) is followed by FLEE at
  0.25 m/s into the walls; the walls loom, each burst starts a new escape + flee and raises arousal,
  so flights lengthen (cascade 68-116 s). C3 front PASS (FREEZE 0.1 s -> escape 0.2 s, 0.96 -> 1.58 m),
  left PASS (0.91 -> 1.47 m; v6 1.01 -> 1.06 m), right FAIL on the known onset flaw (response 2.3 s;
  escape then 0.94 -> 1.51 m). REST never occurred in simulation (simulated DNp09 stays 32-50 Hz),
  so rest is untested here. 0 contacts in all scenarios.
- stage3_009 (amendment 7, decoder v8: bursts during FLEE steer the flight, no arousal from own
  flight): C1 PASS (min 0.89 m), C2 PASS (1 defensive onset, one 3.3 s flight, 0 contacts),
  C3 front PASS (FREEZE 0.1 s -> escape, 0.96 -> 1.58 m), left PASS (0.91 -> 1.47 m), right FAIL on the
  known onset flaw (escape 2.3 s after the far-away onset; then 0.94 -> 1.51 m). 0 contacts anywhere.
  Stage 3 formally FAILED (person_right, as in stage3_005-007). REST untested in simulation.
- stage5_007 (amendment 4: decoder v8, keep-in slow zone, 0.25 m hard stop, exclusion circle):
  drive 505 s, ended early by the operator's request for more roaming. Contacts: not reported.
  Path 57 m, 11.5 m2. States: REST 48 %, FLEE 15 %, FORWARD/TURN 15 %, HOLD 11 %, ESCAPE 11 %, FREEZE
  3 bouts (0.1-0.5 s). 87 FLEE bouts, displacement up to 0.76 m. DNp09 ~30 Hz while walking, ~10 Hz
  standing still or turning in place: no intrinsic walking drive in the model. Keep-in: slow zone
  active 243 cycles; reached 0.30 m outside while standing still at the edge (pose flicker
  0.25 <-> 0.29 m, one map cell), over the 0.25 m criterion -> FAILED by 0.05 m. Before the drive a
  server bug (event text on a refused drive) was fixed under a lock revision; the robot was nudged
  0.6 m by a manual command (brain off) because the charger area is unknown space in the map.
- stage3_010 (amendment 8, decoder v9: endogenous exploration drive + flights up to 20 s): 0 contacts
  everywhere. C1 PASS (min 0.88 m). C2 FAIL: 4 defensive onsets in 120 s (limit 3); roam_open was
  EXPLORE 38 %, FLEE 27 % (flights 9.5-12.5 s), FORWARD 21 %, ESCAPE 9 %, min clearance 0.45 m -- more
  walking meets more walls, whose looming triggers escapes. C3 front PASS (escape 0.2 s, 0.94 ->
  1.59 m, then a 9.5 s flight), left PASS (0.95 -> 1.43 m), right FAIL on the known onset flaw.
- stage5_008 (amendment 5, decoder v9 with endogenous exploration drive): 1204 s, ended by the
  20 min budget (battery 45 -> 31 %). Contacts: not yet reported. Path 216 m, 58.8 m2 visited
  (x -17.0..0.5, y -5.0..6.6) vs 89 m / 18.5 m2 in stage5_006. States: FLEE 34 %, EXPLORE 24 %,
  HOLD (stale input) 16 %, ESCAPE 12 %, FORWARD 9 %, REST 2 %, FREEZE 1 %. 177 escape programs,
  18 freezes, 20 rests; flights are fragmented by stale-input windows in the records (116 pieces
  >= 1 s, up to 1.07 m each). Keep-in: max 0.35 m beyond the allowed edge -> criterion (0.25 m)
  FAILED. Robot left crouched at (-15.1, 5.8).
- stage6_001 (planner + fly reflexes, simulation, 3 seeds x 2 arms, 120 s): FAILED (arrival).
  0 contacts in all six runs; no reflex before the person appeared; first takeover 2.8-3.0 s after
  the person appeared (when it was ~0.6 m away). Neither arm arrived within 120 s: the planner arm
  detoured round the standing person and was 0.27 m from the goal at 120 s (it needs ~120 s);
  the reflex arm stayed near the person: 5 takeovers per seed (e.g. 10.9, 65, 82, 99, 119 s) --
  each time the planner's detour brought the robot back toward the person, the approach loomed
  and the brain escaped again (reflex/planner oscillation). Min distance to the person 0.42-0.44 m
  (reflex) vs 0.50 m (planner). Server code was nevertheless deployed at the operator's request
  (brain mode starts off; reflexes only on the toggle).
- stage6_002 (amendment 1: 0.6 m planner keep-out for 30 s after a reflex, 180 s): FAILED (arrival
  1 of 3 in the reflex arm; planner arm 3 of 3 in ~121 s). 0 contacts everywhere, no early takeover.
  Reflex arm still 3-5 takeovers per seed, at 0.67-0.85 m from the standing person: the keep-out
  radius was clipped to the robot's gap at takeover time (~0.25 m), so detours still passed close.
