# Stage 4 protocol — shadow mode on the real robot, run stage4_001

Locked before execution (protocol_lock_stage4_001.sha256). Stage 3 did not pass (RESULTS.md);
the user chose to proceed to shadow mode anyway. Stage 4 sends no brain command to the chassis:
the server runs brain mode 'shadow', which computes and logs the command it would execute
(after envelope and limits) and never writes it to the command path. Stage 5 needs a separate
decision by the user and its own protocol.

Code: brain_service.py (decoder v4), brain.py, retina.py (LidarRetinaV3), envelope.py, decoder.py,
config/loom_registry.json; SLAM server server.py + brain_link.py (deployed copy: SPEED_HARD_MAX
stays 1.0 as currently deployed; the local 2.0 change is not part of this deploy).
Server started with XT_BRAIN_DIR=<loom_005>, XT_MAX_V default, the robot standing or crouched still,
charger may stay connected, chassis may be off.

Trials (a person walks toward the robot at normal walking pace, stops about 0.7 m away, waits 3 s,
walks off): T1 front x3, T2 left x3, T3 right x3, T4 robot alone 60 s (nobody moving nearby).
Trial times are written down by the operator; the analysis uses them only to cut windows.

Measured (from runs/stage4_001/brain_windows.jsonl and the server telemetry type='brain'):
- M1 live timing: brain window p50/p95 (ms), input age p50/p95 at window start, fraction of stale windows.
- M2 per approach: first ESCAPE/ESCAPE_PROGRAM/BACK_OFF window and its time relative to the
  first loom window; for side approaches whether the escape turn points away from the person.
- M3 still scene (T4): fraction of ESCAPE windows (false escapes).
- M4 shadow integrity: no 'brain' command reached the chassis (mode stayed 'shadow';
  server cmd stayed zero apart from operator commands).

Pass criteria for going on to a stage 5 proposal: M4 holds; stale windows <= 10 %; M3 <= 5 %;
a reaction within 1.0 s of loom onset in at least 2 of 3 trials per direction.
Stage 4 passing does not open physical execution by itself.

## Amendment 1 — run stage4_002, locked before execution

stage4_001 kept as recorded. Fault: in shadow mode no geofence is set and brain_link.command()
unpacked self.fence (None) on the first window with fresh input (21:03:34), raising TypeError that
stopped the server's control loop; no shadow records were logged by the server after that and the
server's own lease/battery handling was not running (chassis locked; the bridge stops on missing
commands). The brain service log (runs/stage4_001/brain_windows.jsonl) is complete. One exploratory
free-form segment (E1, operator disturbances, 313 s) was recorded in stage4_001 before the fault
was found; it is reported separately and is not a protocol trial.
Change: brain_link.py skips the geofence when none is set; server.py catches any brain-link error in
the control loop (command zero, recorded as withheld). Trials and criteria unchanged.
