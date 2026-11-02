# Navigation method

Implementation: `flyhead/navigation/planning.py` (route planning, pure functions),
`flyhead/navigation/nav.py` (`Navigator`: route following and the host safety chain),
`flyhead/slam/navmap.py` (map layers). Rebuilt on 2026-10-08; the previous
implementation is in git history (`flyhead/navigation/nav.py` at the baseline commit).

## Reference point

Everything is planned and controlled on the robot's **turning point**: the point
that stays fixed when it turns in place. It was fitted from 47 in-place turns in
four runs (`live_20261008T103347` … `T113059`): 0.11 m behind the LiDAR along the
body (`nav.REFERENCE_BODY = (-0.11, -0.01)`, `slam.TURN_POINT_LIDAR`), residual
under 1 cm. The previous code controlled a "body centre" 0.45 m *ahead* of the
LiDAR, i.e. 0.56 m in front of the turning point. Every turn then swung the
controlled point sideways (0.45 m per 46°), which caused the start-up rocking,
false "arrived" results while turning, tour cancellations for deviation, and the
real body cutting inside every curve. The body footprint is a 0.35 m disc about
the turning point (0.5–0.7 m wide robot).

## Layers

* **Static:** the map package grid (0.05 m) and height layers. A cell blocks a
  robot of height *H* when an occupied height bin lies below *H* + 0.10 m.
* **Live:** decayed hits (×0.92 per scan) of returns between 0.08 m and the
  robot height within 8 m, after a per-scan floor fit (a trimmed plane through
  the scan's near-floor returns removes the session's vertical drift). A cell is a
  live obstacle at 3 decayed hits; "new" obstacles exclude cells within 0.1 m of
  static structure.
* **Changes:** persistent differences (≥ 0.03 m², 1.5 s) are committed as
  `added` / `removed`, versioned in `runs/<id>/cloud_map/`, and enter planning.

## Planning: centreline routes

Routes follow the centreline of the free space, where the nearest obstacles on
both sides are equally far away. Between two walls a route keeps equal clearance
on both sides; it never runs along one wall.

1. **Clearance** *d*: distance to the nearest blocked or unknown cell.
2. **Centreline**: the λ-medial axis with λ = 0.8 m: a cell is on it when its
   nearest obstacle point and a neighbour's lie on opposite walls at least λ
   apart, so wall roughness does not create spurious branches. Only cells with
   *d* ≥ 0.45 m count.
3. **Offset ratio** *r* = *m* / (*m* + *d*), *m* = distance to the centreline:
   0 on the centreline, towards 1 at a wall.
4. **A\*** on a 0.10 m grid, 8-connected without corner cutting. Step cost
   1 + 39 *r*²; cells with *d* < 0.45 m are never entered (hard clearance =
   0.35 m body radius + 0.10 m). A start inside the hard clearance leaves
   through cells with ≥ 0.25 m clearance within 1.5 m (cost 30). An unreachable
   goal snaps to the nearest reachable cell within 1 m.
5. **Smoothing** inside the centreline band: Laplacian smoothing plus a small
   pull toward the centreline; a point moves only if its offset ratio stays
   within max(0.12, its current ratio) and its clearance does not drop. Routes
   are resampled at 0.05 m with per-point curvature and clearance.

**Tour loop** (`compute_loop`): the outline of the robot's centreline network
with its enclosed faces filled runs along the outermost cycle and traces branches
out and back. Whole branches up to 3 m deep are cut (a *maximal fold*: the two
legs coincide within 0.4 m and diverge just outside it). Deeper branches stay in
the tour as out-and-back excursions along their centreline. Centreline on
weakly mapped ground (< 60 % known within 1 m) is excluded. The entry point and
direction minimise distance plus turning against the robot's heading; the
approach is a centreline route and the return is the approach reversed. The plan
uses the measured height + 0.10 m.

In the current map the gaps west of the central block are narrower than 0.9 m,
so the only true cycle is the 16 m one around the eastern obstacle; the tour
(71 m loop from the usual start) adds the corridors to the north-west, west and
south as out-and-back excursions.

## Route following

A committed route is never re-planned on a timer. It changes only when

* a new obstacle on the route is **confirmed**: within 0.40 m of the route in
  the next 3 m for 3 consecutive control cycles (cleared after 1 s free). The
  robot approaches it to 0.5 m of arc at most and a **local detour** is spliced
  in: a centreline route from the robot (within 6 m) to the route 0.8–4 m
  beyond the obstacle, at most 3 × the replaced length + 2 m, retried at most
  every 3 s. The confirmed live obstacles enter the clearance field itself, so
  the detour runs on the centreline between the obstacle and the walls (with
  the static field alone, smoothing pulled the detour back through the
  obstacle);
* the robot has been more than 0.5 m off the route for 2 s: a short **rejoin**
  route to 1.0–3.5 m ahead is spliced in. More than 1.5 m off stops the task.

Progress is an arc-length projection within a bounded window (0.3 m back,
≥ 0.3 m ahead per cycle; 1.5 m back after a recovery reversal), so a route that
passes the same place twice never jumps. **Cusps** (out-and-back turnarounds,
heading change > 120° within ±0.15 m) bound both the window and the pursuit
target: the outbound and return legs lie on one line there, and projection
cannot tell them apart. Within 0.15 m of a cusp progress steps across and the
robot turns in place onto the return leg. Arrival needs both the remaining arc
and the end-point distance within 0.20 m (goals) or 0.30 m (tours).

## Control (10 Hz)

1. **Gates:** missing chassis status, invalid source time, pose or obstacle
   layer older than 3 s (held, resumed after 5 fresh frames), low fitness
   (occlusion wait). While the chassis reports a crouched body the robot height
   is the fixed crouch height; otherwise it is the LiDAR height above the map
   floor + 0.12 m, and a tour holds for up to 10 s, then stops, if that exceeds
   the planned height (a floor-estimate error used to cancel tours at once).
2. **Host safety chain:** swept free travel of the body disc along the route
   is checked out to 2.5 m; the allowed speed is the highest *v* whose
   reaction + braking distance, *v* × 0.6 s + *v*² / (2 × 0.20 m/s²), fits in
   the free travel minus 0.35 m (0.75 m in total at 0.30 m/s; the same rule
   caps the approach to a confirmed blockage). Both constants are commanded-
   speed figures and are not yet replaced by measured stops; standing, the
   robot moves 1.3–2× the command, so treat them as optimistic. Chassis guard
   < 0.15 m → stop; stall (forward command, no motion for 2 s) → stop. Blocked
   for 8 s without a detour → reverse up to 0.6 m at 0.08 m/s (rear clear),
   wait 2 s, re-plan; after 3 cycles at one place hold for the operator. Goal
   tasks give up after 60 s blocked; tours wait.
3. **Pure pursuit** on the route: lookahead 0.5 + 4 s × speed, at most 1.0 m;
   κ = 2 sin α / *L*. Speed = min(v_max, max(0.06, ω_max / max route curvature
   over the next 0.6 m) — the floor keeps a route kink from pinning the
   speed at 0.02 m/s, which does not move the robot —, clearance cap (half speed at 0.45 m route clearance, full at
   0.8 m), 0.5 × remaining arc, pose-age cap (zero at 1 s), heading scale),
   then limited so that κ v ≤ ω_max (tracking turn rate, default 0.20,
   operator ceiling 0.60 rad/s).
4. **Turns in place:** above 50° heading error the robot brakes to zero, then
   turns at ≤ ω_rotate (default 0.12, ceiling 0.30 rad/s) until the error is under 12°. Beyond ±150° the turn
   direction is held (the error's sign is noise there). Because the reference is
   the turning point, a turn in place no longer moves the controlled pose.
5. **Rate limits** on the previous command: linear +0.10 / −0.20 m/s², angular
   +0.8 / −1.2 rad/s², Δt ≤ 0.2 s; ω reversals go through zero.

**Operator limits** (`tour`, `explore`, `go_home` or `nav_params` with `v`,
`w`, `wr`) apply live. `v` is clamped to the ceiling `XT_MAX_V` (default 0.30 m/s, never above 1.0), which the
server passes to the bridge. A tour
with `laps` (1–20) re-plans from the current pose after each completed lap;
Stop, a manual takeover, a failed lap or battery below 15 % ends the series.
The console's **Full loop** button (Home and Mission ribbons) opens the
laps / speed / turn-rate dialog.

Tuned on 2026-10-08, standing, four laps of ~130 m:

| Lap | v / w / ω_rotate | Time | Mean speed | Peak measured |
|---|---|---|---|---|
| 1 | 0.15 → 0.25 ramp | 12.5 min | 0.17 m/s | 0.32 m/s |
| 2 | 0.25 / 0.40 / 0.20 → 0.16 | 10.1 min | 0.22 m/s | 0.40 m/s |
| 3 | 0.30 / 0.40 / 0.16 | 10.2 min | 0.21 m/s | 0.43 m/s |
| 4 | 0.30 / 0.55 / 0.16 | 9.3 min | 0.23 m/s | 0.45 m/s |

Above 0.30 m/s (2026-10-08, standing, `XT_MAX_V=0.6`; emergency stops on the
9.7 m lane (2.6, 4.6) → (11.3, 7.8), measured from the 10 Hz control records):

| v_max | Peak command | Peak measured | At the stop | Stop distance / time |
|---|---|---|---|---|
| 0.30 | 0.30 | 0.42 m/s | 0.37 m/s | 0.38 m / 1.46 s |
| 0.40 | 0.39 | 0.49 m/s | 0.42 m/s | 0.32 m / 1.96 s |
| 0.50 | 0.49 | 0.57 m/s | 0.23 m/s | 0.28 m / 1.48 s |
| 0.60 | 0.58 | 0.69 m/s | 0.45 m/s | 0.43 m / 1.73 s |
| 0.60 | 0.57 | 0.63 m/s | 0.63 m/s | 0.74 m / 1.42 s |

The two clean stops fit ≈ 0.8 s reaction (pose age included) + 0.8 m/s²
braking. The stop rule (0.6 s, 0.20 m/s², on the commanded speed) asks for
1.15 m at 0.57 commanded, against 0.74 m measured, so it remains conservative
even with the standing speed gain; it is left unchanged. Higher speeds are
reached only on straights: the centreline weaves ±0.7 m through this lane and
the curve cap brings the speed down to 0.1–0.4 m/s at each bend, and the
0.10 m/s² acceleration needs ~2 m to reach 0.5 m/s. Not yet tested: laps above
0.30, stops above 0.63 m/s, crouched runs above 0.30.

Full laps above 0.30 (same evening, standing, w 0.55, ω_rotate 0.16, one lap each
from the charger):

| v_max | Route | Time | Mean | Peak measured | Tracking p95 / max | Turning in place | Detours |
|---|---|---|---|---|---|---|---|
| 0.30 (lap 4 above) | 126.5 m | 9.3 min | 0.23 m/s | 0.45 m/s | 0.17 / 0.35 m | 15 % | 0 |
| 0.40 | 131.0 m | 8.8 min | 0.25 m/s | 0.53 m/s | 0.20 / 0.34 m | 23 % | 0 |
| 0.50 | 135.0 m | 9.0 min | 0.25 m/s | 0.65 m/s | 0.33 / 0.48 m | 30 % | 0 |
| 0.60 | 135.2 m | 10.6 min | 0.21 m/s | 0.73 m/s | 0.44 / 0.72 m | 39 % | 6 |

0.40 m/s is the fastest lap. Above it the robot overshoots each bend (pure
pursuit with a turn-rate cap cannot turn tighter, and the curve cap only looks
0.6 m ahead), the heading error passes 50° and it stops to turn in place; at
0.60 every detour was a rejoin after a > 0.5 m overshoot, not an obstacle.
Faster laps need braking before bends (a longer curvature look-ahead sized to
the stopping distance), not a higher ceiling.

Tracking error median 0.05–0.06 m throughout. Turns in place at 0.20 rad/s
dropped fitness to 0.78 (p10 0.82, against 0.94 at 0.16), so 0.16 rad/s is
the standing spin limit. Above 0.25 m/s the lap time is bound by turns in
place (15–24 % of the time) and the curve cap, not by v_max; the driving
turn rate (0.55) was the last setting that helped.

**Turbo** (`nav_params` / `tour` with `turbo: true`; console **Turbo** button or the Full-loop
dialog, after a checklist) drives laps up to 1.0 m/s *measured*, for show rather than lap time:

* *Speed profile:* per route point v ≤ √(0.5 m/s² / κ) and ≤ 0.8 rad/s / κ, with κ the heading
  change over a 1 m chord (pointwise centreline curvature is mostly wiggle), then capped by
  route clearance (0.25 m/s at 0.45 m, 0.45 at 0.80, full at 1.20 m) and swept backwards at
  0.35 m/s² so the robot brakes *before* each bend. The controller takes the profile minimum
  over the next v × 0.6 s.
* *Measured speed:* the command is divided by a running measured/commanded gain (learned on
  steady straights, starting at 1.3 when standing); an over-speed governor trims the command
  while the estimate catches up.
* *Stop rule:* 0.8 s + v² / (2 × 0.5 m/s²) on the measured speed (measured: 0.8 s, 0.8 m/s²);
  swept range 3.0 m. Fitness < 0.85 drops to 0.30 m/s; the pose-age ramp is 0.35–0.70 s.
* *Pursuit:* lookahead up to 1.8 m, shortened in bends so its chord cuts at most 0.08 m.
* Outside Turbo the speed limit is at most 0.40 m/s. The console offers Turbo only when the
  server's nav status reports `turbo`, and its top speed is the server ceiling × gain.

Simulation (closed loop, speed gain 1.25, 0.8 m/s² physical acceleration, tour_east):

| Run | Lap | Peak | Tracking p95 / max | Body clearance min | Notes |
|---|---|---|---|---|---|
| plain 0.40 | 560 s | 0.50 | 0.17 / 0.27 m | 0.45 m | identical before and after the Turbo change |
| plain 0.60 | 521 s | 0.74 | 0.17 / 0.32 m | 0.47 m | |
| Turbo 1.0 (first version) | 560 s | 0.74 | 0.32 / 0.49 m | **0.20 m** | 1.8 m lookahead cut a corner |
| Turbo 1.0 | 500 s | 0.99 | 0.09 / 0.17 m | 0.47 m | |
| Turbo 1.0, gain 1.0 / 1.6 | 496 / 517 s | 0.95 / 1.02 | ≤ 0.17 / 0.26 m | ≥ 0.45 m | 1.6: 1.2 s above 1.03 before the faster gain learning |
| Turbo, box on the route | 561 s | 1.04 | 0.09 / 0.17 m | box 0.42 m | stopped, detoured |
| Turbo, box on the fastest stretch | 569 s | 0.94 | 0.09 / 0.16 m | box 0.19 m (plain 0.40: 0.28) | braked from 0.94, detoured |

On the robot (2026-10-08, standing, `XT_MAX_V=1.0`, w 0.55, ω_rotate 0.16, one lap each):

| Run | Route | Time | Peak measured | Tracking p95 / max | Turning in place | Detours |
|---|---|---|---|---|---|---|
| plain 0.40 (reference) | 131.0 m | 8.8 min | 0.53 m/s | 0.20 / 0.34 m | 23 % | 0 |
| plain 0.60 (reference) | 135.2 m | 10.6 min | 0.73 m/s | 0.44 / 0.72 m | 39 % | 6 |
| Turbo 0.6 | 131.8 m | 8.7 min | 0.67 m/s | 0.19 / 0.32 m | 29 % | 0 |
| Turbo 0.8 | 125.9 m | 8.4 min | 0.85 m/s | 0.28 / 0.46 m | 34 % | 0 |
| Turbo 1.0 | 128.0 m | 7.7 min | 0.95 m/s | 0.23 / 0.39 m | 27 % | 0 |

**Incident, 2026-10-08 23:09 (two-lap Turbo series, lap 2).** Near (−7.6, −1.6), at 0.56 m/s
command (≈ 0.75 measured) with a 0.37 rad/s turn, fitness fell 0.95 → 0.5 and the live pose
slipped ≈ 0.5 m; the map correction found the 0.41 m fix but rejected it (limit 0.3 m), the
robot steered by the wrong pose, coasted ≈ 0.9 m after the occlusion stop and ended with its
turning point 0.35 m from a mapped obstacle at (−6.3, −0.25). The same recording replayed
offline does not slip (fitness ≥ 0.94, no frame drops live either), so the slip is a live,
non-reproducible event; the safeguards below catch a slip whatever its cause:

* Turbo bends: planned lateral acceleration 0.15 m/s² (was 0.5) and measured v × turn rate
  ≤ 0.18 m/s·rad/s while driving (the incident ran at ≈ 0.28).
* Turbo fitness: full speed at ≥ 0.95, falling linearly to 0.30 m/s at 0.85.
* Any mode: fitness < 0.80 → crawl at 0.15 m/s.
* Drift alarm (`slam.py`): two consecutive corrections rejected only for their size
  (0.3 m / 5°) that align well (fitness ≥ 0.85 after, ≥ 0.05 better) raise
  `map_correction.drift`; while the robot moves the server cancels the task, ends a lap
  series, zeroes the command and relocalizes (`Session.check_drift`). Tested with base-map
  scans shifted 0.45 / 0.20 m: fires on the second rejection.

Simulation with these limits: Turbo lap 569 s (was 500 s), peak 0.81 m/s, tracking max 0.17 m;
injected drift on a straight (fitness 0.97 → 0.60 and 0.5 m over 4 s) → 0.15 m/s within 2 s.

Lane stops in Turbo: 0.74 m/s peak → 0.71 m; 0.77 m/s peak → 0.81 m in 1.76 s (the Turbo rule
budgets 2.15 m at 1.0). Learned speed gain 1.34. Fitness stayed ≥ 0.82; the largest
tracking errors are turns in place at sharp corners, in open space.

Every cycle writes `nav_decision` (pose, progress, tracking error, target,
command, clearances, blockage, route revision, reason) to `navigation.jsonl`.

## Simulation

`sim2.py` (development harness, not in the repository) drives the real
`Navigator` in closed loop: the robot turns about its turning point with the
LiDAR 0.11 m ahead, scans are ray casts on the navigation grid (occlusion
included), commands pass a 0.25 s first-order lag, poses carry 1 cm / 0.3° noise
and 0.1 s latency. It reports true body clearance, centreline offset, tracking
error, turn-direction flips and route revisions. Results are in `docs/history.md`.

## References

1. Macenski, Singh, Martin, Ginés. *Regulated Pure Pursuit for Robot Path Tracking.*
   Autonomous Robots, 2023. <https://arxiv.org/abs/2305.20026>
2. Chaussard, Couprie, Talbot. *Robust skeletonization using the discrete
   λ-medial axis.* Pattern Recognition Letters, 2011.
3. Choset, Burdick. *Sensor-based exploration: the hierarchical generalized
   Voronoi graph.* IJRR, 2000 (centreline roadmaps).
