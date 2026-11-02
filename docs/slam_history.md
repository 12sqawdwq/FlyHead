# History, lessons and open issues

The detailed per-session working log (Chinese, 2026-09-25 to 2026-10-07) is
preserved in git (`refs/backup/pre-english-refactor-20261007`, file
`mem/WORKING_STATE.md`) together with the earlier README. Measurement receipts
stay in the unversioned `logs/` folder.

## Current state and open issues (2026-10-07)

* **Map coverage is the blocker.** The base map covers 45.6 × 46.3 m but only
  366.8 m² is known (82.6 % unknown, 29 interior holes). Relocalization fails
  outside the mapped region (fitness stuck near 0.72), and tours stop there.
  Decision: rebuild the base map with a new mapping session.
* An automatic mapping drive ("scheme A": compute the tour on the old map, start a
  fresh session, transform the route into the new frame, drive it) exists only as
  ad-hoc scripts in `/tmp/xt-loop-test/` on the compute server, not in this
  repository. A fresh session's initial yaw was measured at about 179°, so the
  frame transform must use measured poses, never an assumed zero yaw.
* The robot last reported crouched at 26 % battery with an unstable link; a return
  to the charger had not completed.
* The chassis driver modifications (report-only guard, posture admission) live in
  `~/diablo_ws` on the robot and are not versioned here.
* The compute server's `/home` is 99 % full (12 GB free); recording stops at the
  8 GiB reserve.
* The deployed copies predate this refactor (see the README).

## Timeline

| Date | Milestone |
| --- | --- |
| 09-25 | Survey: robot reachable only through the compute server. Bridge + server with KISS-ICP, IMU rotational deskew and raw.xt recording. Found the L1 LiDAR mounted backwards (`BODY_YAW_DEG = 180`). First base map `nav_20260925_01`, rebuilt as `_03` with height layers and body filtering. |
| 09-25 | Navigation v1 (A*, pure pursuit, live change detection), posture calibration (LiDAR 0.20 m crouched / 0.33–0.41 m standing), first autonomous explore-and-return (7 cm end error), high-speed runs, first tour attempts. |
| 09-26 | Moved the whole stack onboard to work without network; the Pi was not real-time (200–340 ms/frame). Fixed an OpenBLAS deadlock and several Pi stalls. |
| 10-04 | RPP-style controller with turn hysteresis and rate limits; control-cycle telemetry; diagnosis showed CPU contention on the Pi, not the network, as the bottleneck. |
| 10-05 | Faster obstacle publication, 3 s freshness gates, manual relocalization, fixed-map console, map artifact editor and the corrected base map now in use. |
| 10-05/06 | Whole-route tour (one continuous route, no waypoints), local detours, network-independent autonomy. |
| 10-06 | Distributed architecture: compute on the 5090D, robot I/O only, PC console; SLAM in its own process; bounded transport; command deadlines with a clock anchor; posture confirmation from chassis feedback; link-loss return along the driven path; supervised `auto_tour.py`. |
| 10-06/07 | Best tour: 35.46 m of 213 m with 6 detours. Guard made report-only with one host-side decision chain; narrow-space recovery (reverse 1.0–1.2 m, wait, re-plan) for every task. |
| 10-07 | Repository refactor: single deployment mode, English throughout, legacy paths removed. |
| 10-08 | Root cause of the tracking failures found: the controlled point was 0.56 m ahead of the robot's turning point (fitted from 47 turns in place). Navigation rebuilt: centreline routes (λ-medial axis), pursuit on the turning point, no timer replanning, debounced detours, cusp handling. |

## Navigation rebuild (2026-10-08)

Closed-loop simulation (`sim2.py`: robot turning about its measured turning point,
LiDAR 0.11 m ahead, occlusion-aware grid scans, 0.25 s command lag, 1 cm / 0.3°
pose noise, 0.1 s latency), same map, same tour starts, v_max 0.10 m/s:

| Tour start | Navigator | Result | Body edge to obstacle, min | Centre offset ratio, median / p90 | Route revisions |
| --- | --- | --- | --- | --- | --- |
| (10.46, 2.71) facing E | previous | cancelled at 9.1 m: deviation > 0.75 m | 0.14 m | 0.14 / 0.28 | 1 |
| (10.46, 2.71) facing E | rebuilt | complete, 72.0 m in 1075 s | 0.15 m | 0.00 / 0.07 | 1 |
| (10.05, 2.86) facing W | previous | stuck after 17.6 m: "reversed 4 times … waiting for the operator" | −0.10 m (contact) | 0.24 / 0.52 | 0 |
| (10.05, 2.86) facing W | rebuilt | complete, 72.8 m in 1100 s | 0.15 m | 0.00 / 0.07 | 1 |

A box placed on a goal route: detour around it on the centreline between box and
wall, arrival in 90 s, 3 route revisions (initial plan + 2 detours as more of the box
became visible). The 0.15 m minimum is the narrowest passage of the map (0.50 m
turning-point clearance). Median turning-point clearance on the tour: 1.10 m
(previous loop: 0.52 m). Not yet verified on the robot.

## Localization drift fix (2026-10-08)

The first standing tour on the rebuilt navigation (`live_20261008T123504`) stopped
at 33.8 m: map agreement fell gradually from 0.99 to 0.51 and a fresh
relocalization put the robot 0.62 m from its estimate. An offline replay of the
recording through the SLAM engine reproduced it exactly (end error 0.62 m). The
drift was mostly heading (about 2° over 25 m). Applying the body-return sphere
while standing, or pushing base-map anchor points every 0.5 m instead of 2 m,
changed nothing: KISS-ICP keeps at most 6 points per voxel and its own scans fill
the voxels around the robot first, so the base map barely constrained the pose.

Fix (`slam.py`, *continuous map correction*): about once per second the current
scan is aligned to the base map (levelled ICP); a confident result (fitness ≥ 0.7,
not worse than before, ≤ 0.3 m, ≤ 5°) is applied at half strength to the
session→map transform. Replay of the same recording: end error 0.08 m, standing
fitness mean 0.972 (p10 0.94; the one dip is a person next to the LiDAR). Live,
crouched: 2,171 corrections applied, 0 rejected, each a few millimetres, fitness
0.97–0.998. Live, standing, after a robot restart (warning 2048 cleared;
`live_20261008T164708`): the whole 71.2 m tour completed in 11.3 min with one
route (no replans), 582 corrections applied and 0 rejected, fitness mean 0.981
(p5 0.932, end 0.993), tracking error median 0.06 m / p95 0.20 m / max 0.35 m,
31 turn-direction flips. 64 s of the run were holds for stale poses (up to 8.7 s)
and chassis-status gaps: link/LiDAR stalls on the robot side, still open.

## Lessons worth keeping

* "Sent" is not "done": SDK result codes (even 255) and ROS publication do not
  prove an action. Confirm postures by chassis feedback and motion by pose change.
* The chassis exits silently with code 0 when it cannot obtain control
  authority; an SDK that delivers telemetry may still not accept commands until
  the robot is power-cycled.
* Crouch requests need `up=0` on every later frame because the driver repeats the
  last frame.
* Pure rotation faster than about 0.12 rad/s made the pose estimate jump up to 250°
  and 1 m per sample; the in-place rate is capped for that reason.
* Control the point the robot actually turns about. The old 0.45 m "body centre"
  ahead of the LiDAR was a sign error: the turning point is 0.11 m *behind* it. Every
  workaround for orbiting targets, turn grace periods and re-attachment came from
  that one offset. Fit it from in-place turns, and simulate with the same geometry
  (the old simulator turned the robot about the controlled point and hid the bug).
* Near a 180° heading error the error's sign is noise; a sign that follows it caused
  52 flips and 90 s of spinning.
* A tour must not be cancelled by transient conditions (stale pose, missing chassis
  status, standing idle); hold and resume instead. Each cancellation of that kind
  ended a lap in the field.
* Mixed-posture trajectories bias the floor reference of the map exporter and
  *shrink* the known area; re-deriving a grid is not automatically an improvement.
* Fixed-display and live data must not share one channel: the console loads the
  saved map once and only streams the pose.
* On the Pi, the camera took about half a core and shared USB with the LiDAR; it is
  off by default.
* `inf` is not JSON; the guard stopped reporting entirely when one field became infinite.
