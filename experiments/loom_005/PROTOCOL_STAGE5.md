# Stage 5 protocol — brain drive on the real robot, run stage5_001

Locked before execution (protocol_lock_stage5_001.sha256). Physical execution authorised by the
user in chat ("finish stage5 ... tell me to do the test"; standing posture requested). Stage 3 did
not pass (side escapes did not gain distance); stage 4 passed with a short still segment. The user
accepts running decoder v4 unchanged with the limitations listed in RESULTS.md (direction locked
1.5 s per escape program, chained escapes, open-space turn jitter, fitness-gate pauses).

Chain: LiDAR -> SLAM pose + world points -> LidarRetinaV3 -> full connectome (brain_service.py,
decoder v4) -> brain_link.py -> normal server command path (0.3 s lease, clock anchor, battery
stop) -> robot bridge -> chassis. No planner, route or constant speed is involved. The brain
decides motion; brain_link may only withhold, reduce or zero it:
- limits 0.15 m/s forward, 0.10 m/s back, 0.40 rad/s;
- envelope (envelope.py) on the real speed: standing multiplies the command by 1.35 before the
  stop rule and divides it out after;
- geofence 2.0 m around the pose where drive starts (outside it only motion back toward the centre);
- zero when the brain window is older than 0.35 s, its input older than 0.45 s, the scan older than
  0.45 s, localization fitness < 0.80, or on any brain-link error.
Any manual command, Stop, or a navigation task ends drive (brain falls back to shadow).

Setup: off the charger, standing (the user's choice; standing moves ~1.35x the command and needs
~0.8 s to react), open area >= 2.5 m in every direction, operator holding the RC throughout.
Server restarted with XT_CHASSIS_DISABLED=0 XT_REMOTE_MOTION_ENABLED=1, XT_MAX_V default 0.30,
XT_BRAIN_DIR=<loom_005>. Brain service run stage5_001.

Segments (operator announces start and end in chat):
- D1 explore: 120 s, nobody within 2.5 m.
- D2 approaches: front x2, robot-left x2, robot-right x2, walking pace, stop about 0.7 m from the
  robot, wait 3 s, step away sideways; >= 10 s between approaches.
- Abort: any RC takeover, contact, or operator call; drive is switched off and the segment ends.

Measured (server telemetry type='brain' with executed v, w, pose, envelope; brain_windows.jsonl):
- P1 safety: contacts (operator report), RC takeovers, minimum scan clearance to the body edge,
  envelope / fence / gate interventions (% of cycles).
- P2 exploration (D1): path length, area covered, fraction of cycles moving, time at the fence.
- P3 escapes (D2): reaction after loom onset; direction relative to the threat side; nearest
  return on the threat side at onset vs 3 s later.
Success for this first drive: 0 contacts, 0 safety-forced RC takeovers. P2/P3 are reported, not
pass/fail. A failure is recorded; any change is a new amendment and a new run.

## Amendment 1 — run stage5_002, locked before execution
stage5_001 kept as recorded: 0 contacts, 0 RC takeovers, but (a) the robot was crouched for the
whole run (the server's 60 s idle auto-crouch fired while waiting for the operator's go, 16 s
before drive started), and (b) every escape happened at the 2 m fence edge, where the forward part
was zeroed; executed escapes were in-place turns of 12-25 deg. D2 ended after 53 s for the fix.
Changes: decoder v5 (stage 3 amendment 4; frontal reverse 0.20 m/s, lateral 0.80 rad/s with
0.12 m/s forward, 2.0 s; trigger and side choice unchanged), only if stage3_006 has 0 contacts;
brain_link: escape programs limited to 0.15 / -0.20 m/s and 0.80 rad/s (other states unchanged)
and may run 0.5 m past the fence (2.5 m = the cleared radius); server: standing idle crouch
waits 300 s instead of 60 s while the brain drives. Procedure: stand the robot immediately before
switching to drive and confirm standing in the first drive records. Segments and criteria unchanged.

## Repeat — run stage5_003, locked before execution
Same code and settings as stage5_002 (lock hashes identical apart from this protocol file); a
replication requested by the operator. The escape fitness-gate change was proposed but not applied.

## Amendment 2 — run stage5_004, locked before execution
stage5_003 kept as recorded (loom -> escape decision median 0.35 s, 4 of 12 looms untriggered).
Operator asked for faster, much more visible escapes and approved the escape limits in chat.
Changes: decoder v6 (stage3_007: 0 contacts); brain_link escape limits 0.20 / -0.30 m/s, 1.0 rad/s
and escape fitness gate 0.50 (only while ESCAPE_PROGRAM; other states unchanged at 0.15 / -0.10 m/s,
0.40 rad/s, fitness 0.80). Envelope, server 0.30 m/s ceiling, fence (+0.5 m during escapes),
stale-input stops and RC takeover unchanged. Segments and criteria unchanged.

## Repeat — run stage5_005, locked before execution
Same code and settings as stage5_004 (decoder v6, escape limits 0.20 / -0.30 m/s, 1.0 rad/s, escape
fitness gate 0.50); lock hashes identical apart from this protocol file. Requested by the operator
("v6 go"). The frontal/lateral hysteresis fix is not applied. Segments and criteria unchanged.

## Amendment 3 — run stage5_006, locked before execution
stage5_005 kept as recorded (escapes better; the standing robot crept to 3.43 m from the fence
centre with forward speed zeroed, because in-place turns displace it). The operator asked to let
the robot roam the whole mapped area and chose "Whole mapped area" over a watched room or a bigger
circle, accepting that the area (166.6 m2 of free floor) cannot be cleared and that the live-scan
envelope plus the operator following with the RC are the only guards against people and new
obstacles.
Changes (brain_link only; decoder v6, limits, envelope, stale and fitness gates unchanged):
- drive with area='map' replaces the circle by a map keep-in: known (not unknown) static-map cells
  >= 0.30 m from obstacles that block the standing height, the connected region containing the start
  pose; drive is refused if the robot is not inside it. Escapes may run 0.15 m outside it.
- outside the fence or keep-in, translation is allowed only back inside (as before) and turning only
  toward the inside (new; stops the turn creep); beyond the allowed edge by > 0.40 m nothing moves.
Segment: D1 free roam from the operator's go until the operator says finished, at most 20 min,
battery >= 30 %; operator follows with the RC; people may walk past or approach as they like.
Measured: P1 as before plus keep-in interventions and maximum distance outside it; P2 path length,
area covered, fraction of cycles moving, time at the keep-in edge; P3 escapes as before.
Success: 0 contacts, 0 safety-forced RC takeovers, robot never > 0.40 m outside the keep-in.

## Amendment 4 — run stage5_007, locked before execution
stage5_006 kept as recorded (0 contacts; 0.46 m outside the keep-in > 0.40 limit; frozen 4.5 min at
low localization fitness). The operator asked for a robot that sometimes stops where it is,
sometimes answers a disturbance with a sustained flight, and sometimes wanders.
Changes:
- decoder v8 (stage3_009: 0 contacts; C1, C2, C3 front/left pass; C3 right fails on the known onset
  flaw as in every run since stage3_005): REST / FREEZE / escape with side hysteresis / FLEE whose
  length grows with arousal (decoder-side leaky count of threat onsets, not connectome activity).
- brain_link: FLEE may use the escape limits (0.20 m/s forward) but keeps the 0.80 fitness gate and
  the normal keep-in; within 0.30 m of the keep-in edge, speed toward it is scaled down to 25 %;
  hard stop 0.25 m outside (was 0.40); cells within 1.0 m of (1.6, 7.1) left out of the keep-in
  (config/keepin_exclude.json, stage5_006 fitness < 0.88).
Segment: D1 as amendment 3 (whole-map keep-in, operator follows with the RC, at most 20 min,
battery >= 30 %), including approaches and walk-pasts at the operator's choice.
Success: 0 contacts, 0 safety-forced RC takeovers, never > 0.25 m outside the keep-in.
Reported: REST / FREEZE / ESCAPE / FLEE counts and durations, flight length vs arousal, path, area.
Lock revision (before any drive of stage5_007): server.py crashed formatting the event when the
brain refused drive (fence None); the event line now skips the fence text on a refusal. No other
change. Lock re-written as protocol_lock_stage5_007.sha256 (previous kept as ..._rev0).

## Amendment 5 — run stage5_008, locked before execution
stage5_007 kept as recorded (ended early; REST 48 %; 0.30 m outside the keep-in while standing at
the edge -> criterion failed by 0.05 m). The operator asked for more spontaneous roaming and long,
fast flights, chose the decoder-side endogenous exploration drive, and accepted stage3_010's two
failures (C2: 4 defensive onsets > 3; C3 right: known onset flaw; 0 contacts everywhere).
Change: decoder v9 only (LOOM_DECODER=9). brain_link, server, limits (flight 0.20 m/s), keep-in
rules unchanged from amendment 4. Segment and criteria as amendment 4.
