# Stage 6 protocol — planner + fly reflexes (brain mode 'reflex')

Operator request (2026-10-11): combine the fly brain's real-time obstacle avoidance with the
existing centreline planner / full-loop exploration, with web controls: planner avoidance always
on, fly reflexes and Turbo as optional toggles.

Layers (kept separate in every record):
- planner: server/planning.py + nav.py (centreline A*, tours, live obstacle layer, stop rule,
  pursuit about the turning point). Drives every navigation task.
- fly reflex: retina (band points farther than 0.20 m from mapped obstacles, so walls the planner
  already knows are not shown) -> full connectome -> decoder v9 -> brain_link. Takes over only
  while the decoder state is FREEZE or ESCAPE_PROGRAM and no gate withholds it (stale input,
  fitness, envelope); escape limits 0.20 / -0.30 m/s, 1.0 rad/s; live-scan envelope applies.
- after a reflex: the navigator holds while the brain commands (0.3 s lease), then a goal task
  replans from the new pose and a tour splices back onto its route (gives up after 15 s).
The decoder's REST / FLEE / EXPLORE states are not executed in reflex mode.

## Simulation run stage6_001 (sim_reflex.py), locked before execution
Real-time closed loop on the 5090D: the server's Navigator and BrainLink unchanged, a live brain
service (decoder v9) on a separate port, map onboard_20260926_manual_cleanup_20261005, start
(7.0, -1.1), goal = Navigator.pick_explore_goal(6-10 m), v_max 0.30 m/s, standing gain 1.34.
At 8 s a person (r 0.25 m) appears 3.0 m ahead on the route and walks toward the robot at
0.5 m/s, stopping for good 0.7 m from it. Arms: reflex, planner (brain in shadow). Seeds 1, 2, 3.
Development runs (stage6_dev, not evidence): seed 1 showed the envelope used the wall-filtered
points (a lateral escape reached 0.13 m from a wall); fixed (envelope sees every point, only the
retina is filtered). After the fix: reflex arm 0 contacts, first takeover 2.8 s after the person
appeared (the giant fibre fires only when the person is close), neither arm arrived within 70 s
because the person stays on the route. Hence, set before stage6_001: duration 120 s, and the
reaction criterion is "a takeover after the person appears" (no 1.0 s bound).
Criteria (reflex arm): 0 contacts (turning point < 0.35 m from a wall cell or the person) in all
seeds; 0 reflex takeovers before the person appears; >= 1 takeover after the person appears in
>= 2 of 3 seeds; the task ends 'arrived' in >= 2 of 3 seeds. Reported for both arms: minimum
distance to the person, time to arrival, reflex count, takeover latency.

## Amendment 1 — run stage6_002, locked before execution
stage6_001 kept as recorded (0 contacts; arrival FAILED in both arms; reflex arm oscillated: the
planner's detours led back past the standing person, whose looming triggered 5 escapes per seed).
Changes: when a reflex takes over, the navigator blocks a disc of 0.60 m around the nearest
unmapped scan point (brain_link threat_xy) for 30 s in every plan made meanwhile (never over the
robot itself); the simulation calls it exactly as server.py does. Duration 180 s (the planner arm
needed ~120 s with the person on its route). Criteria unchanged.

## Amendment 2 — run stage6_003, locked before execution
stage6_002 kept as recorded. Changes: the keep-out disc keeps its full 0.60 m radius and is only
shrunk at planning time where it would cover the robot itself; while a keep-out is active the
retina also ignores scan points within it + 0.30 m (habituation to a threat already escaped; the
live-scan envelope and the planner's stop rule still see those points). Criteria unchanged.
