<div align="center">

<img src="docs/media/banner.png" alt="FlyHead banner" width="100%">

<p>
<img src="https://img.shields.io/badge/connectome-FlyWire%20v783-3fb950?style=flat-square" alt="FlyWire v783">
<img src="https://img.shields.io/badge/neurons-138%2C639%20LIF-58a6ff?style=flat-square" alt="138,639 LIF neurons">
<img src="https://img.shields.io/badge/PyTorch-CUDA-ee4c2c?style=flat-square&logo=pytorch&logoColor=white" alt="PyTorch CUDA">
<img src="https://img.shields.io/badge/ROS%202-Foxy-22314e?style=flat-square&logo=ros&logoColor=white" alt="ROS 2 Foxy">
<img src="https://img.shields.io/badge/SLAM-KISS--ICP-6e7781?style=flat-square" alt="KISS-ICP">
<img src="https://img.shields.io/badge/status-research%20code-d29922?style=flat-square" alt="research code">
</p>

<p>
<b>English</b> · <a href="README.zh-CN.md">中文</a> ·
<a href="#1-demonstrations">Demonstrations</a> ·
<a href="#2-state-coverage">State coverage</a> ·
<a href="#11-quick-start">Quick start</a> ·
<a href="docs/demo.md">Demo page</a> ·
<a href="docs/architecture.md">Architecture</a> ·
<a href="docs/verification.md">Verification</a> ·
<a href="experiments/README.md">Experiments</a>
</p>

</div>

FlyHead is a research robot with **two decision layers in one body**:

| | |
| --- | --- |
| **Autonomous navigation** | LiDAR SLAM on a saved map of the building, centreline route planning, tours, detours and a host safety chain. Works on its own, without the brain. |
| **Fly brain** | The complete FlyWire v783 *Drosophila* connectome on a GPU turns LiDAR looming into escape, turning and walking through identified descending neurons. A safety envelope may only reduce or zero its commands. |

Hardware: a DIABLO wheel-legged robot (Raspberry Pi 4B, ROS 2 Foxy, Unitree L1 LiDAR), a GPU compute host
and a Windows operator PC. *Xingtian (刑天) fights on after losing his head; here a fly brain is the head.*

---

## 1. Demonstrations

<p>
<img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> physical robot (phone footage) &nbsp;
<img src="https://img.shields.io/badge/REAL%20LOG-3fb950?style=flat-square" alt="REAL LOG"> the robot's own logs, replayed &nbsp;
<img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> the saved SLAM map of the real building &nbsp;
<img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> simulated LiDAR, full connectome on GPU &nbsp;
<img src="https://img.shields.io/badge/CONSOLE-a371f7?style=flat-square" alt="CONSOLE"> real console and server, replayed session
</p>

### 1.1 The real robot

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/nav_hallway.gif" width="400" alt="hallway">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <b>Video 1.</b> <b>Autonomous navigation · hallway</b></p>
<p><sub>Standing / crouched posture and route driving, no fly brain · 19 s · <a href="docs/media/real/hallway_posture_drive.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/nav_office.gif" width="400" alt="office at night">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <b>Video 2.</b> <b>Autonomous navigation · office at night</b></p>
<p><sub>Route driving through the mapped office, no fly brain · 6 min at 4× · <a href="docs/media/real/office_night_drive_4x.mp4">mp4</a></sub></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/real_brain.gif" width="400" alt="brain drive">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <b>Video 3.</b> <b>The fly brain drives · stage5_004</b></p>
<p><sub>A person approaches; 262 s of brain drive, 30 escape programs, 0 contacts reported · <a href="docs/media/real/stage5_004_brain_drive_escape.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/tour.gif" width="400" alt="real tour replay">
<p><img src="https://img.shields.io/badge/REAL%20LOG-3fb950?style=flat-square" alt="REAL LOG"> <b>Video 4.</b> <b>Autonomous tour, from the robot's log</b></p>
<p><sub>2026-10-04 · 729 s, 56.1 m, fitness ≥ 0.963 · <a href="docs/media/realmap/real_tour_729s.mp4">mp4</a> · <a href="docs/media/realmap/real_tour_138s.mp4">138 s tour</a></sub></p>
</td>
</tr>
</table>

### 1.2 The real site: SLAM map

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/mapbuild.gif" width="400" alt="map build-up">
<p><img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> <b>Video 5.</b> <b>The mapping session, replayed</b></p>
<p><sub>2026-09-25 · 1,407 s, 54.7 m, 550,975 points · <a href="docs/media/realmap/slam_map_build.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/orbit.gif" width="400" alt="3-D point cloud">
<p><img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> <b>Video 6.</b> <b>The saved point cloud in 3-D</b></p>
<p><sub>Walls and furniture below 1.3 m, coloured by height · <a href="docs/media/realmap/slam_map_orbit.mp4">mp4</a></sub></p>
</td>
</tr>
</table>

<a href="docs/media/realmap/nav_layers.png"><img src="docs/media/realmap/nav_layers.png" width="100%" alt="navigation layers"></a>

**Figure 1.** Navigation layers of the saved SLAM map: occupancy grid · clearance field and the centreline every route follows · obstacle heights (what blocks a crouched or a standing robot) · the mapping path and the real tours.

### 1.3 The fly brain on the real map

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/decision.gif" width="400" alt="decision chain">
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b>Video 7.</b> <b>The decision chain, window by window</b></p>
<p><sub>A person from the left: LiDAR → LC4/LPLC2/LC9 → descending neurons → decoder → command · <a href="docs/media/realmap/decision_person_left.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/roam.gif" width="400" alt="free roaming">
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b>Video 8.</b> <b>120 s of free roaming</b></p>
<p><sub>18.9 m, 0 contacts; explore, escape, flee, freeze and hold in one run · <a href="docs/media/realmap/decision_roam_open.mp4">mp4</a></sub></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/stage6.gif" width="400" alt="stage 6">
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b>Video 9.</b> <b>Stage 6: planner vs. fly reflexes</b></p>
<p><sub>Both arms arrive with 0 contacts; the brain takes over twice · <a href="docs/media/realmap/stage6_planner_vs_reflex.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/console.gif" width="400" alt="operator console">
<p><img src="https://img.shields.io/badge/CONSOLE-a371f7?style=flat-square" alt="CONSOLE"> <b>Video 10.</b> <b>Operator console on the real map</b></p>
<p><sub>Relocalized at fitness 1.00, brain in shadow mode, charging lock on · <a href="docs/media/realmap/console/console_real_map_brain_shadow.mp4">mp4</a></sub></p>
</td>
</tr>
</table>

### 1.4 All eight brain scenarios on the real map

| Scenario | What happens | Brain: contacts, min clearance | Blind: contacts | Video |
| --- | --- | --- | --- | --- |
| `person_front` | a person walks at the robot, stops 0.7 m away | 0, 0.69 m | 0 | [mp4](docs/media/realmap/decision_person_front.mp4) |
| `person_left` | the same from the left | 0, 0.70 m | 0 | [mp4](docs/media/realmap/decision_person_left.mp4) |
| `person_right` | the same from the right | 0, 0.56 m | 0 | [mp4](docs/media/realmap/decision_person_right.mp4) |
| `wall_ahead` | a lane toward a far wall | 0, 0.88 m | 0 | [mp4](docs/media/realmap/decision_wall_ahead.mp4) |
| `roam_open` | 120 s free roaming | 0, 0.45 m | 0 | [mp4](docs/media/realmap/decision_roam_open.mp4) |
| `loom_front` | an object at 0.6 m/s that never stops (stress test) | 37, −0.23 m | 19 | [mp4](docs/media/realmap/decision_loom_front.mp4) |
| `loom_left` | the same from the left | 21, −0.23 m | 19 | [mp4](docs/media/realmap/decision_loom_left.mp4) |
| `loom_right` | the same from the right | 21, −0.23 m | 19 | [mp4](docs/media/realmap/decision_loom_right.mp4) |

The `loom_*` objects drive through the robot whatever it does: the brain escapes, the object follows. They
count contacts and are not passed scenarios.

<a href="docs/media/realmap/scenarios_brain_vs_blind.png"><img src="docs/media/realmap/scenarios_brain_vs_blind.png" width="100%" alt="brain vs blind"></a>

**Figure 2.** Every scenario on the real SLAM map: the fly brain's path coloured by decoder state, the blind baseline dashed, the person or object track in orange; contacts and minimum clearance per run.

<a href="docs/media/realmap/decoder_states.png"><img src="docs/media/realmap/decoder_states.png" width="100%" alt="decoder states"></a>

**Figure 3.** Decoder state over time in each brain run (simulation on the real map, decoder V9).


### 1.5 The four console tabs

<table>
<tr>
<td width="50%" valign="top"><a href="docs/media/realmap/console/tab_home.png"><img src="docs/media/realmap/console/tab_home.png" width="400" alt="Home"></a><br><sub><b>Home</b> · session, map, tours</sub></td>
<td width="50%" valign="top"><a href="docs/media/realmap/console/tab_mission.png"><img src="docs/media/realmap/console/tab_mission.png" width="400" alt="Mission"></a><br><sub><b>Mission</b> · goals, limits, brain modes</sub></td>
</tr>
<tr>
<td width="50%" valign="top"><a href="docs/media/realmap/console/tab_drive.png"><img src="docs/media/realmap/console/tab_drive.png" width="400" alt="Drive"></a><br><sub><b>Drive</b> · chassis, posture</sub></td>
<td width="50%" valign="top"><a href="docs/media/realmap/console/tab_display.png"><img src="docs/media/realmap/console/tab_display.png" width="400" alt="Display"></a><br><sub><b>Display</b> · views, map changes</sub></td>
</tr>
</table>

The console and server are real; the session is a replay whose scans were taken from the saved point cloud
along a scripted path, with a person added. Shown: relocalization, posture (stand, LiDAR 0.45 m), the person
committed as a map change, and the brain's shadow decisions (HOLD, EXPLORE, TURN_LEFT/RIGHT, REST, FORWARD).

### 1.6 Provenance of each clip

* The brain clip is matched to its run by the phone's recording time (22:57:17 local, inside the drive window
  22:53:38–22:58:03). The two navigation clips carry file timestamps of 2026-10-08, the day the navigation
  stack was rebuilt.
* The tour replays are rendered from the console's observation logs of the real robot
  (`standing_tour_*_20261004*.jsonl`): every frame is one recorded navigator message. They ran on the navigation
  stack of 2026-10-04, four days before the rebuild.

  | Tour | Driven | Navigator states (messages) | Fitness |
  | --- | --- | --- | --- |
  | 729 s | 56.1 m | driving 454, waiting 68, stopped 11, avoiding 5, planning 1 | min 0.963, median 0.995 |
  | 138 s | 12.6 m | driving 104, idle 26, waiting 8, stopped 4, planning 1 | min 0.910, median 0.995 |

* The map was built on 2026-09-25 (912 × 926 grid at 0.05 m) and cleaned up by hand on 2026-10-05. The map package
  itself is not in the repository; only rendered views of it, published with the site owner's consent.
* Stage 6: planner arm arrived after 122.1 s; reflex arm after 139.7 s with 2 takeovers (39 windows under the
  brain). Another run with the same seed timed out at 180 s with 0 contacts.
* Earlier synthetic-arena clips: [decision chain](docs/media/sim/decision_chain_person_front.mp4) ·
  [stage 6](docs/media/sim/stage6_planner_vs_reflex.mp4) · [console](docs/media/console/console_replay_brain_shadow.mp4).
* Sources and renderers for every item: [docs/demo.md](docs/demo.md).

---

## 2. State coverage

| Layer | State | Shown in |
| --- | --- | --- |
| Navigator (real logs) | `driving`, `waiting`, `stopped`, `avoiding`, `planning`, `idle` | Video 4 (state band, robot colour) |
| Navigator (simulation) | `driving`, `arrived`, reflex hold | Video 9 |
| Navigator gates | stale pose (wait), detour (`avoiding`), waypoint progress | Video 4 (reason line) |
| Localization | relocalized on the saved map (fitness 1.00); fitness along a real tour | Video 10; Video 4 |
| Posture | crouch, stand | Videos 1, 4, 10 |
| Map changes | new obstacle committed, temporary obstacle cleared | Video 4 (boxes); Video 10 (messages) |
| Decoder | FORWARD, EXPLORE, TURN_LEFT, TURN_RIGHT | Videos 7, 8 and every scenario |
| Decoder | FREEZE, ESCAPE_PROGRAM, BACK_OFF, FLEE | Videos 7, 8; person and loom scenarios; Video 3 (real robot) |
| Decoder | HOLD, REST | Video 8 (HOLD); Video 10 (HOLD, REST) |
| Brain mode | `off` | Videos 1, 2, 4 |
| Brain mode | `shadow` | Video 9 (planner arm); Video 10 |
| Brain mode | `drive` | Video 3 (real robot) |
| Brain mode | `reflex` | Video 9 (reflex arm) |
| Safety | charging lock on | Video 10 |
| Safety | envelope reducing a brain command | decision videos, panel 3 ("envelope:"); loom scenarios, `person_right`, Video 8 |

---

## 3. System overview

```text
                 ┌────────────── compute host (GPU) ──────────────────────────────────┐
LiDAR + IMU ───► │ SLAM (KISS-ICP) ─► relocalize on saved map ─► planner ─► command    │──► robot ──► wheels
 (robot)         │        │                                    ▲        │             │   (0.3 s lease)
                 │        └─► virtual retina ─► brain service ─┘ reflex  ▼             │
                 │            LC4/LPLC2/LC9 ─► connectome (138k LIF) ─► decoder ─► safety envelope
                 └─────────────────────────────────────────────────────────────────────┘
operator PC: web console (Start LiDAR, goals, tours, Turbo, brain modes) ── SSH tunnel ──► server
```

The control server never loads torch: it talks to the brain service over local TCP. Encoders and
decoders are plain NumPy, and the robot bridge does not import the package. Module boundaries are in
[docs/architecture.md](docs/architecture.md).

---

## 4. What is real, what is simulated, what is a claim

| Layer | It is | It is not |
| --- | --- | --- |
| Connectome model | FlyWire v783 LIF model from [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) at a pinned commit, unmodified equations | a calibrated fly; no learning |
| Stimulus encoders | engineering proxies: angular expansion from LiDAR → LC4/LPLC2, free space ahead → LC9 | retinal or visual reconstruction |
| Neuron identity | exact `cell_type` → `root_id` → model index, annotation SHA-locked (`configs/fly/loom_registry.json`) | synonym unions across named types |
| Decoder | fixed formulas on descending-neuron rates (escape program, turn, walk, rest) | a navigation script or a constant drive |
| Navigation | classical SLAM + centreline planner + pure pursuit, works without the brain | the brain's decision, or a neural result |
| Execution | intent after the safety envelope, geofence and keep-in | planner output passed off as neural |

Anatomical side, LiDAR field side and robot yaw sign are kept as three separate tables. The registry
marks the field→eye assignment and the yaw sign as **not calibrated**.

---

## 5. Autonomous navigation (no brain)

The classical layer runs on its own; it is what the robot does when the brain mode is `off`. Full method:
[docs/navigation_method.md](docs/navigation_method.md); operations: [docs/slam_operations.md](docs/slam_operations.md).

### 5.1 Sensors and body model

| Item | Value | Notes | Code |
| --- | --- | --- | --- |
| LiDAR | Unitree L1, ~10 Hz clouds | streamed as binary frames over SSH stdout; mounted facing backwards (body forward = LiDAR −x) | `robot/bridge.py`, `lidar_slam.BODY_YAW_DEG = 180` |
| IMU | 200 Hz | gravity levelling at session start; per-scan deskew | `flyhead/slam/lidar_slam.py` |
| Reference point | turning point, 0.11 m behind the LiDAR | fitted from 47 in-place turns, residual < 1 cm; replaces a body centre 0.56 m ahead of it | `nav.REFERENCE_BODY = (-0.11, -0.01)` |
| Body footprint | disc of radius 0.35 m | about the turning point; robot 0.5–0.7 m wide | `envelope.BODY_R` |
| Posture | crouch / stand | from LiDAR height above the map floor; self-returns removed by a learned mask | `flyhead/slam/lidar_slam.py` |

### 5.2 Mapping and localization

| Stage | Method | Thresholds | Code |
| --- | --- | --- | --- |
| Odometry | KISS-ICP in a child process | first frame 2 s of points; then 0.2 s sub-cloud batches | `flyhead/slam/slam_process.py` |
| Deskew | IMU orientation interpolated per point | frames wait for IMU coverage, then run undeskewed | `lidar_slam.imu_deskew` |
| Relocalization | global search on the base map | accept: fitness ≥ 0.8 and best/second ratio ≥ 1.3; hint: within 1 m and 30° | `flyhead/slam/reloc.py` (`MIN_FIT`, `MIN_RATIO`) |
| Localization gate | navigation refused until localized | fitness < 0.6 for 1 s cancels a task | `flyhead/navigation/nav.py` |
| Map correction | pose corrected against the base map while driving | corrections > 0.3 m or 5° rejected; two well-aligned rejections raise a drift alarm | `lidar_slam.py`, `Session.check_drift` |
| Map changes | persistent differences vs. the base map | ≥ 0.03 m² for 1.5 s → committed as `added` / `removed` | `flyhead/slam/navmap.py` |

**Map package** (`maps/<name>/`, not committed; renders in [Section 1](#1-demonstrations)):

| File | Content |
| --- | --- |
| `map.pgm`, `map.yaml` | occupancy grid, 0.05 m cells (0 occupied, 254 free, 205 unknown) |
| `map.ply` | the saved point cloud |
| `floor.npy` | per-cell floor height |
| `obst_hmin.npy`, `obst_hmax.npy`, `obst_bins.npy` | lowest / highest obstacle point above floor, 16 height bins of 0.15 m |
| `MAP_INFO.json` | frame definition, source session, lineage, grid statistics |

### 5.3 Route planning (centreline routes)

| Step | Definition | Parameter |
| --- | --- | --- |
| Clearance *d* | distance to the nearest blocked or unknown cell | — |
| Centreline | λ-medial axis of free space | λ = 0.8 m; only cells with *d* ≥ 0.45 m |
| Offset ratio | *r* = *m* / (*m* + *d*), *m* = distance to the centreline | 0 on the centreline, → 1 at a wall |
| Search | A\* on a 0.10 m grid, 8-connected, no corner cutting | step cost 1 + 39 *r*²; *d* < 0.45 m never entered |
| Smoothing | Laplacian smoothing inside the centreline band | resampled at 0.05 m with curvature and clearance |
| Tour loop | outermost cycle of the centreline network; branches out and back | branches ≤ 3 m cut; current map: 71 m loop |

### 5.4 Route following

| Event | Condition | Action |
| --- | --- | --- |
| New obstacle on the route | within 0.40 m of the route, next 3 m, 3 control cycles | approach to ≤ 0.5 m, splice a local detour (retry ≤ every 3 s) |
| Off the route | > 0.5 m for 2 s | splice a rejoin route 1.0–3.5 m ahead |
| Far off the route | > 1.5 m | stop the task |
| Cusp (turnaround) | heading change > 120° within ±0.15 m | turn in place onto the return leg |
| Arrival | remaining arc and end-point distance | ≤ 0.20 m (goal), ≤ 0.30 m (tour) |

### 5.5 Control loop (10 Hz)

| Stage | Rule | Values |
| --- | --- | --- |
| Gates | chassis status present, pose and obstacle layer fresh, fitness adequate | stale > 3 s holds; resumes after 5 fresh frames |
| Pure pursuit | lookahead 0.5 + 4 s × speed | ≤ 1.0 m; κ = 2 sin α / *L* |
| Speed | min of operator ceiling, curvature cap, clearance cap, 0.5 × remaining arc, pose-age cap | half speed at 0.45 m route clearance, full at 0.8 m; κ·v ≤ ω_max |
| Turn in place | heading error > 50° | brake, turn at ≤ 0.12 rad/s (ceiling 0.30) until < 12° |
| Rate limits | on the previous command | linear +0.10 / −0.20 m/s²; angular +0.8 / −1.2 rad/s² |

### 5.6 Host safety chain

| Stage | Rule |
| --- | --- |
| Free travel | swept body disc along the route, checked to 2.5 m |
| Speed from travel | highest *v* with *v* × 0.6 s + *v*² / (2 × 0.20 m/s²) ≤ free travel − 0.35 m |
| Chassis guard | < 0.15 m → stop (report-only on the robot; enforced by the host) |
| Stall | forward command, no motion for 2 s → stop |
| Blocked | 8 s without a detour → reverse ≤ 0.6 m at 0.08 m/s, wait 2 s, re-plan; 3 cycles → hold for the operator |
| Give-up | goal tasks after 60 s blocked; tours wait |

The stop constants are commanded-speed estimates; standing, the robot moves 1.3–2× the command.

### 5.7 Speed modes

| Mode | Ceiling | Bends | Stop rule | Fitness scaling |
| --- | --- | --- | --- | --- |
| Plain | `XT_MAX_V` (default 0.30, ≤ 0.40 m/s outside Turbo) | curvature cap over the next 0.6 m | 0.6 s + *v*² / (2 × 0.20 m/s²), commanded speed | < 0.80 → 0.15 m/s |
| Turbo | 1.0 m/s measured | profile *v* ≤ √(0.15 m/s² / κ), braking before bends | 0.8 s + *v*² / (2 × 0.5 m/s²), measured speed | full ≥ 0.95, 0.30 m/s at ≤ 0.85 |
| Laps | 1–20 laps, re-planned each lap | — | stop, manual takeover, failed lap or battery < 15 % ends the series | — |

### 5.8 Measured performance (2026-10-08, standing, real robot)

| Run | v_max | Route | Lap time | Mean | Peak measured | Tracking p95 / max | Turning in place | Detours |
|---|---|---|---|---|---|---|---|---|
| Plain | 0.30 | 126.5 m | 9.3 min | 0.23 m/s | 0.45 m/s | 0.17 / 0.35 m | 15 % | 0 |
| Plain | 0.40 | 131.0 m | 8.8 min | 0.25 m/s | 0.53 m/s | 0.20 / 0.34 m | 23 % | 0 |
| Plain | 0.50 | 135.0 m | 9.0 min | 0.25 m/s | 0.65 m/s | 0.33 / 0.48 m | 30 % | 0 |
| Plain | 0.60 | 135.2 m | 10.6 min | 0.21 m/s | 0.73 m/s | 0.44 / 0.72 m | 39 % | 6 |
| Turbo | 0.6 | 131.8 m | 8.7 min | — | 0.67 m/s | 0.19 / 0.32 m | 29 % | 0 |
| Turbo | 0.8 | 125.9 m | 8.4 min | — | 0.85 m/s | 0.28 / 0.46 m | 34 % | 0 |
| Turbo | 1.0 | 128.0 m | 7.7 min | — | 0.95 m/s | 0.23 / 0.39 m | 27 % | 0 |

| Emergency stop (Turbo lane) | Peak measured | Stop distance | Stop time |
| --- | --- | --- | --- |
| run 1 | 0.74 m/s | 0.71 m | — |
| run 2 | 0.77 m/s | 0.81 m | 1.76 s |

0.40 m/s is the fastest plain lap; above it the robot overshoots bends and stops to turn in place. The Turbo
slip incident of the same evening is listed in [Section 9](#9-known-problems-and-open-issues).

### 5.9 Operator console

| Tab | Controls |
| --- | --- |
| Home | Start LiDAR / End, Save map, Camera, Full loop, Reset runtime, Continue on base map |
| Mission | Set goal / Solve / Stop, Explore, Return, speed and turn-rate limits, Avoidance, Fly reflexes, Turbo, brain Shadow / Roam / Off, Relocalize |
| Drive | Start / Stop chassis, Guard reset, Stand / Crouch |
| Display | Top / Iso / Follow / Clear trail, Commit changes, Auto commit |

| Outline node | Shows |
| --- | --- |
| Base map, Session | loaded map; session type (live / replay) |
| Localization | relocalization state and fitness |
| Chassis | posture and LiDAR height |
| Mission | navigator state and reason |
| Map changes | committed change versions |

### 5.10 Mapping workflow

| Step | Action | Output |
| --- | --- | --- |
| 1 | start with the charging lock (`XT_CHASSIS_DISABLED=1`); Start LiDAR | sensors streaming, no motion |
| 2 | drive a manual session over the building; Save map | `runs/<id>/`: `map.ply`, `trajectory.csv`, `summary.json`, `navigation.jsonl` |
| 3 | `tools/export_session_map.py`; manual cleanup with `tools/correct_map.py` | map package with grid, height layers, `MAP_INFO.json` |
| 4 | start the server with `XT_MAP=maps/<package>` | sessions relocalize and navigate on it |

---

## 6. The fly brain

### 6.1 Pipeline per 100 ms window

| Step | Where | Input → output | Parameters | Code |
| --- | --- | --- | --- | --- |
| Band filter | server, per scan | world points → points 0.08–0.50 m above the floor, body frame | reflex mode drops points ≤ 0.20 m from mapped obstacles | `flyhead/server/brain_link.py` |
| Retina V3 | server | points pooled 0.3 s in world coordinates, 24 bins of 15° → rates | object width 0.30 m; loom gain 600 Hz per rad/s; deadband 0.12 rad/s; LC9 from free space 0.5–2.5 m ahead (≤ 120 Hz); rates ≤ 200 Hz | `flyhead/fly/encoders/lidar_loom.py` |
| Input cells | GPU | rates → Poisson input to LC4, LPLC2, LC9 (left / right) | registry order; stale scan (> 0.30 s) → zero input | `configs/fly/loom_registry.json` |
| Connectome | GPU | 10 × 10 ms blocks, persistent state | 138,639 LIF neurons, 15,091,983 connection records | `flyhead/fly/model.py` |
| Readout | GPU | spike counts of 9 types per anatomical side | DNp01, DNp02, DNp04, DNp06, DNp11, DNp09, DNa01, DNa02, MDN | `Brain.readouts_by_type` |
| Decoder | service | rates → state and intent (*v*, *w*) | V9 (below) | `flyhead/fly/decoders/loom.py` |
| Gates and envelope | server | intent → command | intent > 0.35 s or input > 0.45 s old dropped; fitness ≥ 0.80 (0.50 during escapes); envelope only reduces or zeroes | `brain_link.py`, `flyhead/safety/envelope.py` |

### 6.2 Readouts

| Readout | Decoder variable | Reference rate | Effect |
| --- | --- | --- | --- |
| DNp09 (P9) | forward drive | 60 Hz → 0.15 m/s | walking speed |
| MDN | backward drive | 35 Hz → 0.10 m/s | backing up |
| DNa02 right − left | turn | 20 Hz → 0.40 rad/s | DNa02 right > left turns right (yaw < 0) |
| DNp01 (giant fibre) | escape trigger | burst ≥ 60 Hz (V6+); ≥ 100 Hz escalates a freeze | starts an escape program; side from left/right asymmetry |
| DNp02, DNp04, DNp06, DNp11 | — | — | recorded, not used by the decoder |
| DNa01 | — | — | diagnostic (biased by the forward drive) |

### 6.3 Decoder V9 states

| State | Entered when | Command | Leaves when |
| --- | --- | --- | --- |
| FORWARD / TURN_LEFT / TURN_RIGHT | neural drive above thresholds | *v* from DNp09 − MDN, *w* from DNa02 | drive changes |
| EXPLORE | endogenous walk bout (20–45 s, seeded) and neural *v* < 0.10 m/s | *v* = 0.10 m/s, *w* from DNa02 | pause bout (4–12 s) or a defensive state |
| HOLD | no drive above thresholds | stop | drive returns |
| REST | smoothed DNp09 < 8 Hz (outside walk bouts) | stop | DNp09 > 20 Hz |
| FREEZE | giant-fibre burst while DNp09 < 15 Hz | stop | escalates after 1.5 s or GF ≥ 100 Hz; ends 2 s after GF quiet |
| ESCAPE_PROGRAM | giant-fibre burst ≥ 60 Hz | frontal (\|asym\| < 0.30): reverse 0.30 m/s, then turn away; lateral: 0.20 m/s forward, 1.0 rad/s away | 1.5 s program (turn 2.5 s); side kept unless \|asym\| ≥ 0.45 on the other side |
| BACK_OFF | MDN drive exceeds the forward drive | backward | drive changes |
| FLEE | after an escape program | 0.20 m/s, steering from DNa02 | 6 s + 4 s × arousal, ≤ 20 s |

EXPLORE and the arousal term are decoder-side engineering additions, not connectome activity; records keep
`neural_v` so the neural and endogenous parts stay separable.

### 6.4 Brain modes

| Mode | Brain role | Command limits | Used in |
| --- | --- | --- | --- |
| `off` | none | — | default |
| `shadow` | runs on live scans; intents logged, never sent | — | stage 4 |
| `drive` (console: Roam) | decides motion | 0.15 m/s forward, 0.10 m/s back, 0.40 rad/s; escapes 0.20 / 0.30 m/s, 1.0 rad/s; geofence or map keep-in | stage 5 |
| `reflex` | planner drives; brain takes over on FREEZE / ESCAPE_PROGRAM, then the task replans around a keep-out | brain limits as in `drive` while it is in control | stage 6 |

### 6.5 Neuron registry

| Item | Value |
| --- | --- |
| File | `configs/fly/loom_registry.json` |
| Binding | exact `cell_type` → `root_id` → model index |
| Connectome | FlyWire 783; annotation TSV SHA-256 `9a4f8b2f…` |
| Cells | 513 (LC4 104, LPLC2 210, LC9 179, readouts 20) |
| Rebuild | `tools/build_registry.py`; identical from a fresh clone |
| Not calibrated | field side → eye, robot yaw sign |

---

## 7. Results so far

| Result | Value | Source |
| --- | --- | --- |
| Shadow mode on the real robot (stage 4) | reaction 0.0–0.33 s to 9 operator approaches | `experiments/loom_005`, stage4_002 |
| Brain drive, loom → escape decision (stage 5) | median 0.35 s (0.09–1.08 s); 4 of 12 episodes not triggered | stage5_003 |
| Escape direction | lateral looms turn away from the stronger giant fibre (≤ ~100°); frontal looms reverse | stage 5 runs |
| Contacts in brain drive | 0 in every drive with operator-reported contacts | stage 5 runs |
| Left/right consistency | no swap in LiDAR → body → retina → brain → decoder | stage 4 |
| Brain compute per 100 ms window | 84–110 ms on a shared RTX 5090D (0.9–1.2× real time); 46 ms on an idle GPU | stage 1; [verification](docs/verification.md) |
| Stage 1 reproduction | 629 / 629 recorded rates identical from a fresh clone | [verification](docs/verification.md) |
| Stage 3 (closed-loop simulation) | formally failed on person_right (known evaluation flaw) | stage3_002 – stage3_010 |
| Stage 6 (planner + reflexes, simulation) | passed in stage6_003 | `runs/stage6_003` |
| Real-map simulation suite (V9) | person, wall, roam scenarios: 0 contacts; loom stress tests: 21–37 contacts | [Section 1.3](#13-the-fly-brain-on-the-real-map) |
| EEG → DNa02 (offline) | 24/24 calibration directions; 25/33 accepted replays matched the label | `experiments/eeg_dna02` |

The EEG result validates a direct motor-node pathway, not "the fly understands EEG".

---

## 8. Verification and simulation

| Check | How | Result |
| --- | --- | --- |
| Upstream data identity | `scripts/fetch_upstream.py --annotations` | all files match pinned size and SHA-1 |
| Neuron registry | rebuild from the annotation TSV, compare | 513 cells identical |
| Unit tests | `pytest` (also with only `.[dev]`) | 11 passed |
| Connectome, stage 1 | `tools/repro_stage1.py` vs. the archived record | 629 / 629 identical |
| Refactor equivalence | as-executed `sim_brain.py` vs. `flyhead.sim.loom_sim`, 3 scenarios × V4 / V9 | 366 / 366 windows identical (timing excluded) |
| Stage 3 suite, V9, synthetic arena | 5 scenarios, brain and blind | 0 contacts; C1, C2 pass; person scenarios fail on the onset flaw |
| Control server and SLAM | synthetic recording through `flyhead.server.app --replay` | 77 frames deskewed and levelled, map saved, no errors |
| Stage 6, synthetic arena | 2 arms × 3 seeds with the brain service | STAGE 6 SIM PASSED |
| Stage 6, real map, archived vs. repository code | same map and seed | arrived 139.6 s vs. 139.7 s, 0 contacts, 2 takeovers each |

Details: [docs/verification.md](docs/verification.md). Not covered: `robot/` on hardware and numbers that depend
on the private recorded maps.

---

## 9. Known problems and open issues

These are the problems we know about, from the recorded experiments and from this repository's own
checks. None is a known regression from the repository move: the navigation, SLAM and relocalization
code is identical to the archived version apart from import paths, and the archived and repository
versions of the stage-6 simulation gave the same result on the same map.

| Problem | Status |
| --- | --- |
| **Turbo slip (2026-10-08, real robot).** Pose slipped ≈ 0.5 m at ≈ 0.75 m/s with a turn; the correct fix was rejected by the 0.3 m correction limit and the robot coasted ≈ 0.9 m. | Mitigated (Turbo bend limits, fitness-scaled speed, drift alarm). Root cause not found; a live event that does not reproduce offline. |
| **Correction limit.** The 0.3 m / 5° limit on map corrections rejected a correct 0.41 m fix in the Turbo slip. | Open design question; the drift alarm is the compensation. |
| **Stop distances.** The host's safety constants are commanded-speed estimates; standing, the robot moves 1.3–2× the command. | Open; not yet replaced by measured stops. |
| **Keep-in and fence overshoot** while standing. Several stage-5 criteria failed by 0.05–0.2 m. | Open. |
| **Reflex/planner oscillation near people; no intrinsic walking drive.** | Open. |
| **Stage 6 on the real site map** timed out in one run and arrived in a repeat with the same code and seed. | Run-to-run variation of the real-time simulation, not yet explained. |
| **Relocalization on synthetic recordings.** A recording generated from the arena grid does not match a saved point cloud (about 60 % of wall points agree), so it does not relocalize there. | Test-data limit; real recordings are not affected. |
| **Robot-side code is not in this repository.** The chassis-driver changes (report-only guard, posture admission) live in `~/diablo_ws` on the robot, and the automatic mapping drive ("scheme A") exists only as scripts on the compute server. | Open repository gap; `robot/` is not guaranteed to match what runs on the robot. |
| **Never-stopping looms (`loom_*` stress tests).** On the real map the brain escapes but the object follows, and contacts are higher than the blind baseline in `loom_front` (37 vs 19). | Open: escape distance and direction against a pursuing object. |
| **Licence.** None chosen for FlyHead's own code. | Open; all rights reserved for now. |

---

## 10. Repository layout

| Path | Role | Runs on |
| --- | --- | --- |
| [`flyhead/fly/`](flyhead/fly) | 果蝇: connectome model, encoders (LiDAR loom, EEG), decoders, brain service | GPU host |
| [`flyhead/slam/`](flyhead/slam) | SLAM: KISS-ICP odometry, relocalization, map layers, raw recordings | compute host |
| [`flyhead/navigation/`](flyhead/navigation) | route planning, following, host stop / slow / detour chain | compute host |
| [`flyhead/server/`](flyhead/server) | 服务端: control server, robot session over SSH, control loop, brain link | compute host |
| [`flyhead/safety/`](flyhead/safety) | command envelope (reduce or zero only) | compute host |
| [`flyhead/sim/`](flyhead/sim) | 仿真: closed-loop simulations, synthetic arena, report | any (brain arm: GPU) |
| [`flyhead/monitor/`](flyhead/monitor) | 监视器: operator web console + SSH tunnel | operator PC |
| [`robot/`](robot) | 机器人部署: ROS 2 bridge (LiDAR, IMU, chassis, posture), standalone | robot (Pi 4B, ROS 2 Foxy) |
| [`experiments/`](experiments/README.md) | protocols, locked results and as-executed scripts of every stage | — |
| [`docs/`](docs) | architecture, reproduction, verification, demos, SLAM operations, navigation | — |
| `configs/`, `scripts/`, `tools/`, `tests/` | neuron registry, launchers, map tools, renderers, unit tests | — |

---

## 11. Quick start

### 11.1 Anywhere: unit tests and blind simulation

```bash
git clone https://github.com/12sqawdwq/FlyHead.git && cd FlyHead
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && pytest
python -m flyhead.sim.loom_sim person_front blind 25 runs/blind.jsonl
python -m flyhead.sim.report runs/blind.jsonl
```

### 11.2 With a CUDA GPU (≥ 16 GB free): the connectome in the loop

```bash
pip install -e ".[brain]"
python scripts/fetch_upstream.py                    # pinned fly-brain code + FlyWire v783, identity-checked
python tools/repro_stage1.py runs/repro_stage1      # stage 1: compared with the archived record
python -m flyhead.sim.loom_sim person_front brain 25 runs/brain.jsonl --decoder 9
```

### 11.3 Demo renders

```bash
pip install -e ".[demo]"
python tools/render_demo.py decision runs/decision.mp4 runs/brain.jsonl     # the decision chain
python tools/render_demo.py reflex runs/stage6.mp4 runs/planner.jsonl runs/reflex.jsonl
```

### 11.4 The robot and the control server

Full procedure: [docs/reproduce.md](docs/reproduce.md) (sections 2b and 4) and
[docs/slam_operations.md](docs/slam_operations.md). In short:

```bash
# compute host
XT_ROBOT_HOST=robot XT_ROBOT_ROOT=/home/<user>/FlyHead XT_MAP=maps/<package> bash scripts/start_server.sh
bash scripts/start_brain_service.sh live_001        # optional, for brain modes
# operator PC
XT_COMPUTE_HOST=<alias> python flyhead/monitor/preview.py
```

Physical motion requires `XT_CHASSIS_DISABLED=0 XT_REMOTE_MOTION_ENABLED=1` on the server launch; the
bridge enforces the same two interlocks.

---

## 12. Safety

Physical motion needs two explicit opt-ins on both the compute host and the robot
(`XT_CHASSIS_DISABLED=0`, `XT_REMOTE_MOTION_ENABLED=1`); the default is a charging lock.

| Mechanism | Where | Behaviour |
| --- | --- | --- |
| Command lease | server → bridge | every velocity has a deadline ≤ 0.3 s on the robot clock |
| Keepalive | bridge | no server traffic for 2 s zeroes motion |
| Link-loss return | bridge | after 10 s of silence the applied trace is replayed backwards (≤ 0.20 m/s, ≤ 60 m) |
| LiDAR watchdog | bridge | no scan for 5 s zeroes motion and restarts the LiDAR node (at most 4 times) |
| Freshness | navigator | stale pose or obstacle layer (> 3 s) holds the task |
| Localization | navigator | fitness < 0.6 for 1 s cancels the task |
| Host stop chain | navigator | obstacle ≤ 0.35 m stops, < 0.70 m slows; then detour; then reverse-and-wait |
| Battery | server | < 25 % warns; < 15 % stops navigation, crouches, refuses new tasks |
| Brain envelope | server | intents only reduced or zeroed; geofence and keep-in before the lease |

Commands expire after 0.3 s, the speed ceiling defaults to 0.30 m/s, and an RC supervisor is expected
during any drive. This is research code. See [Known problems](#9-known-problems-and-open-issues).

---

## 13. Documentation index

| Document | What it covers |
| --- | --- |
| `tools/render_real.py`, `tools/render_demo.py` | the renderers for every figure and video, from the logs and the map package |
| [docs/demo.md](docs/demo.md) | every clip: its run, the code and log fields behind each panel, how to regenerate it |
| [docs/architecture.md](docs/architecture.md) | machines, processes, module boundaries, data flow per window |
| [docs/reproduce.md](docs/reproduce.md) | reproduction at four levels, from unit tests to the real robot |
| [docs/verification.md](docs/verification.md) | what was re-run from a fresh clone, with the results |
| [docs/navigation_method.md](docs/navigation_method.md) | navigation: reference point, planning, following, control, Turbo, the slip incident |
| [docs/slam_operations.md](docs/slam_operations.md) | hosts, interlocks, interfaces, map packages, deployment, troubleshooting |
| [docs/slam_history.md](docs/slam_history.md) | working history and open issues of the SLAM and navigation work |
| [experiments/README.md](experiments/README.md) | each experiment: protocol, locked results, as-executed scripts |

---

## 14. Credits and licences

* Connectome model: [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) (GPL-2.0), fetched at a pinned commit, not redistributed here.
* Connectome and annotations: FlyWire (Dorkenwald et al. 2024, Schlegel et al. 2024; [flyconnectome/flywire_annotations](https://github.com/flyconnectome/flywire_annotations)).
* LiDAR odometry: [KISS-ICP](https://github.com/PRBonn/kiss-icp). Web console: [three.js](https://threejs.org) (MIT, vendored with its licence).

No licence has been chosen for FlyHead's own code yet; until one is added, all rights are reserved by the author.

**Topics:** connectome · flywire · drosophila · spiking neural network · LIF · neurorobotics · embodied AI · ROS 2 · LiDAR · looming · escape behaviour · SLAM · navigation · EEG · brain-computer interface · PyTorch · CUDA
