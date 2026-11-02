# FlyHead

**A whole-brain fruit-fly connectome as the head of a wheel-legged robot.**

FlyHead is a research robot stack with two decision layers that share one body:

1. **Autonomous navigation** (no fly brain). The robot maps a building with LiDAR SLAM, relocalizes on
   the saved map, and drives routes: goals, exploration, looped tours, return to the charger, and a
   faster "Turbo" mode. This is the classical layer the brain sits on top of, and it works on its own.
2. **The fly brain.** The complete FlyWire v783 *Drosophila* connectome (138,639 leaky
   integrate-and-fire neurons, 15,091,983 connection records, PyTorch/CUDA) receives encoded LiDAR
   looming and decides escape, turns and walking through identified descending neurons. Its output
   passes only through a safety envelope that can reduce or zero a command, never add one.

Everything runs on a DIABLO wheel-legged robot (Raspberry Pi 4B, ROS 2 Foxy, Unitree L1 LiDAR), a
GPU compute host, and a Windows operator PC. The control server, SLAM and navigation run on the
compute host; the robot only does I/O.

[中文说明](README.zh-CN.md) · [Demos](docs/demo.md) · [Architecture](docs/architecture.md) ·
[Reproduce](docs/reproduce.md) · [Verification](docs/verification.md) · [Experiments](experiments/README.md)

```text
                 ┌────────────── compute host (GPU) ──────────────────────────────┐
LiDAR + IMU ───► │ SLAM (KISS-ICP) ─► relocalize on saved map ─► planner ─► command │──► robot ──► wheels
 (robot)         │        │                                    ▲        │        │   (0.3 s lease)
                 │        └─► virtual retina ─► brain service ─┘ reflex  ▼        │
                 │            LC4/LPLC2/LC9 ─► connectome (138k LIF) ─► decoder ─► safety envelope
                 └─────────────────────────────────────────────────────────────────┘
operator PC: web console (Start LiDAR, goals, tours, Turbo, brain modes) ── SSH tunnel ──► server
```

*Mythology note: Xingtian (刑天) fights on after losing his head. Here a fly brain is the head.*

## Demos

| REAL: brain drive, person approaching (stage5_004) | SIM: the decision chain, window by window |
| --- | --- |
| ![real robot](docs/media/preview/real_stage5_escape.gif) | ![decision chain](docs/media/preview/decision_chain.gif) |
| **SIM: planner vs. fly reflexes (stage 6)** | **CONSOLE: operator console, brain in shadow (replay)** |
| ![stage 6](docs/media/preview/stage6.gif) | ![console](docs/media/preview/console.gif) |

Full clips, the run each one belongs to, and the code behind each panel: [docs/demo.md](docs/demo.md).
Real footage is the physical robot. SIM and CONSOLE clips are labelled and use synthetic LiDAR.

## What is real, what is simulated, what is a claim

| Layer | It is | It is not |
| --- | --- | --- |
| Connectome model | FlyWire v783 LIF model from [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) at a pinned commit, unmodified equations | a calibrated fly; no learning |
| Stimulus encoders | engineering proxies: angular expansion from LiDAR → LC4/LPLC2, free space ahead → LC9 | retinal or visual reconstruction |
| Neuron identity | exact `cell_type` → `root_id` → model index, annotation SHA-locked (`configs/fly/loom_registry.json`) | synonym unions across named types |
| Decoder | fixed formulas on descending-neuron rates (escape program, turn, walk, rest) | a navigation script or a constant drive |
| Navigation | classical SLAM + centreline planner + pure pursuit, works without the brain | the brain's decision, or a neural result |
| Execution | intent after the safety envelope, geofence and keep-in | planner output passed off as neural |

Anatomical side, LiDAR field side and robot yaw sign are kept as three separate tables; the
registry marks the field→eye assignment and the yaw sign as **not calibrated**.

---

## 1. Autonomous navigation (no brain)

This layer is complete on its own and is what the robot runs when the brain mode is **off**.

### 1.1 Sensing and the body model

* **LiDAR:** Unitree L1 on the robot, streamed to the compute host as binary frames over SSH stdout.
  The L1 faces backwards, so the body moves LiDAR −x (`lidar_slam.BODY_YAW_DEG = 180`).
* **IMU:** 200 Hz. Used for gravity levelling at session start and for deskewing each scan.
* **Reference point:** everything is planned and controlled on the robot's **turning point**, the
  point that stays fixed when the robot turns in place: 0.11 m behind the LiDAR, fitted from 47
  in-place turns (residual under 1 cm). Controlling the body centre instead produced sideways swings
  of 0.45 m per 46° of turn; the change is in [docs/navigation_method.md](docs/navigation_method.md).
* **Posture:** crouched or standing, from the LiDAR height above the map floor. The robot's own body
  is masked out of the scan with a learned self-mask.

### 1.2 Mapping and localization

* **Mapping session:** *Start LiDAR* runs KISS-ICP odometry in a child process on the compute host.
  Each scan is deskewed with the IMU when the IMU covers it; otherwise it is processed undeskewed
  after a short wait. Persistent differences from the saved map are committed as versioned obstacle
  changes (`added` / `removed`) and enter planning.
* **Saved map package** (`maps/<name>/`): `map.pgm` / `map.yaml` (0.05 m grid), `map.ply` (the
  saved cloud), height layers (`floor.npy`, `obst_hmin/hmax.npy`, `obst_bins.npy`) and a
  `MAP_INFO.json` with the session lineage. Maps are not committed to this repository: they are
  floor plans of real buildings.
* **Relocalization:** a new session searches the base map for its pose (global search, fitness
  ≥ 0.8, ratio test between the best and second candidate). An operator pose hint can replace the
  ambiguity test for candidates within 1 m and 30° of the hint. Navigation is refused until localized; fitness < 0.6 for 1 s
  cancels a task.
* **Map correction:** while driving, the pose is corrected against the base map. Two consecutive
  corrections rejected only for their size (0.3 m / 5°) that align well raise a drift alarm; the
  server then cancels the task and relocalizes.

### 1.3 Planning: centreline routes

Routes follow the centreline of free space, so between two walls the robot keeps equal clearance
on both sides and never runs along one wall.

1. **Clearance** *d*: distance to the nearest blocked or unknown cell.
2. **Centreline:** the λ-medial axis with λ = 0.8 m, so wall roughness does not create branches.
   Only cells with *d* ≥ 0.45 m count.
3. **Offset ratio** *r* = *m* / (*m* + *d*), where *m* is the distance to the centreline.
4. **A\*** on a 0.10 m grid, 8-connected without corner cutting. Step cost 1 + 39 *r*²; cells with
   *d* < 0.45 m are never entered (hard clearance = 0.35 m body radius + 0.10 m).
5. **Smoothing** inside the centreline band, resampled at 0.05 m with per-point curvature and clearance.

**Tours** (`compute_loop`): the outermost cycle of the centreline network runs as the loop, and
branches are traced out and back. Branches up to 3 m deep are cut; deeper ones stay as out-and-back
excursions. In the current map the tour is a 71 m loop from the usual start.

### 1.4 Following a route

A committed route is never re-planned on a timer. It changes only when:

* **a new obstacle is confirmed** on the route (within 0.40 m of it in the next 3 m for 3 control
  cycles): the robot approaches to 0.5 m at most and a **local detour** is spliced in, retried at
  most every 3 s;
* **the robot is more than 0.5 m off the route** for 2 s: a short **rejoin** route is spliced in;
  more than 1.5 m off stops the task.

Progress is an arc-length projection in a bounded window, so a route that passes the same place
twice never jumps. **Cusps** (out-and-back turnarounds) are handled explicitly: the robot turns in
place onto the return leg. Arrival needs the remaining arc and the end-point distance within
0.20 m (goals) or 0.30 m (tours).

### 1.5 Control (10 Hz)

* **Gates:** a missing chassis status, a stale pose or obstacle layer (> 3 s), or low fitness holds
  the task; it resumes after 5 fresh frames.
* **Pure pursuit:** lookahead 0.5 + 4 s × speed (≤ 1.0 m). Curvature κ = 2 sin α / *L*.
* **Speed:** min of the operator ceiling, a curvature cap, a clearance cap (half speed at 0.45 m
  route clearance, full at 0.8 m), 0.5 × remaining arc, a pose-age cap and a heading scale, then
  limited so κ·v ≤ ω_max.
* **Turns in place:** above 50° heading error the robot brakes to zero and turns at ≤ 0.12 rad/s
  (ceiling 0.30) until the error is under 12°.
* **Rate limits** on the previous command: linear +0.10 / −0.20 m/s², angular +0.8 / −1.2 rad/s².

### 1.6 Host safety chain

The host stops before the chassis guard has to:

| Stage | Rule |
| --- | --- |
| Free travel | swept body disc along the route, checked out to 2.5 m |
| Speed from travel | highest *v* with *v* × 0.6 s + *v*² / (2 × 0.20 m/s²) inside the free travel minus 0.35 m |
| Chassis guard | < 0.15 m → stop (report-only on the robot; the host enforces) |
| Stall | forward command with no motion for 2 s → stop |
| Blocked | 8 s without a detour → reverse up to 0.6 m at 0.08 m/s (rear clear), wait 2 s, re-plan; after 3 cycles at one place, hold for the operator |
| Give-up | goal tasks give up after 60 s blocked; tours wait |

These constants are commanded-speed figures and are optimistic: standing, the robot moves 1.3–2×
the command. They are not yet replaced by measured stops.

### 1.7 Operator limits, laps and Turbo

* **Operator ceiling:** `XT_MAX_V` (default 0.30 m/s, never above 1.0). Turn rates and speed are
  set live from the console *Limits* group.
* **Laps:** a tour with `laps` (1–20) re-plans from the current pose after each lap. Stop, a manual
  takeover, a failed lap or battery below 15 % ends the series. **Full loop** opens the dialog.
* **Turbo** (drives laps up to 1.0 m/s *measured*, after a checklist): a speed profile with
  braking before each bend (lateral acceleration 0.15 m/s² in bends), a measured/commanded speed
  gain learned on straights, a stop rule of 0.8 s + *v*² / (2 × 0.5 m/s²), and fitness-scaled speed
  (full at ≥ 0.95, 0.30 m/s at ≤ 0.85).

### 1.8 Measured performance (2026-10-08, standing, on the robot)

Tuned plain laps of about 130 m (route 126–135 m, four laps at 0.15–0.30 m/s setpoints):

| Setpoint v_max | Route | Lap time | Mean | Peak measured | Tracking p95 / max | Turning in place | Detours |
|---|---|---|---|---|---|---|---|
| 0.30 | 126.5 m | 9.3 min | 0.23 m/s | 0.45 m/s | 0.17 / 0.35 m | 15 % | 0 |
| 0.40 | 131.0 m | 8.8 min | 0.25 m/s | 0.53 m/s | 0.20 / 0.34 m | 23 % | 0 |
| 0.50 | 135.0 m | 9.0 min | 0.25 m/s | 0.65 m/s | 0.33 / 0.48 m | 30 % | 0 |
| 0.60 | 135.2 m | 10.6 min | 0.21 m/s | 0.73 m/s | 0.44 / 0.72 m | 39 % | 6 |

0.40 m/s is the fastest plain lap: above it the robot overshoots bends, its heading error passes
50° and it stops to turn in place. Turbo on the robot, one lap each:

| Run | Route | Time | Peak measured | Tracking p95 / max | Turning in place | Detours |
|---|---|---|---|---|---|---|
| Turbo 0.6 | 131.8 m | 8.7 min | 0.67 m/s | 0.19 / 0.32 m | 29 % | 0 |
| Turbo 0.8 | 125.9 m | 8.4 min | 0.85 m/s | 0.28 / 0.46 m | 34 % | 0 |
| Turbo 1.0 | 128.0 m | 7.7 min | 0.95 m/s | 0.23 / 0.39 m | 27 % | 0 |

Emergency stops (Turbo lanes, measured from the 10 Hz records): 0.74 m/s peak → 0.71 m;
0.77 m/s peak → 0.81 m in 1.76 s. The Turbo budget is 2.15 m at 1.0 m/s.

**Incident, 2026-10-08 23:09 (Turbo lap 2):** near (−7.6, −1.6) at ≈ 0.75 m/s measured with a turn,
fitness fell 0.95 → 0.5 and the live pose slipped ≈ 0.5 m. The map correction found the fix but
rejected it, and the robot coasted ≈ 0.9 m, ending 0.35 m from a mapped obstacle. The same recording
replayed offline does not slip, so the cause is a live, non-reproducible event. The safeguards
added after it (Turbo bend limits, fitness-scaled speed, the drift alarm) are described in
[docs/navigation_method.md](docs/navigation_method.md).

### 1.9 The console (operator PC)

The console is a web page served on the operator PC; the control server stays on the compute host.
Its ribbon has four tabs:

| Tab | What it does |
| --- | --- |
| **Home** | *Start LiDAR* / *End* (session), *Save map*, *Camera*, *Full loop*, *Reset runtime*, *Continue on base map* |
| **Mission** | *Set goal* / *Solve* / *Stop*, *Explore*, *Return*, speed and turn-rate limits, *Avoidance* (planner + stop rule), *Fly reflexes*, *Turbo*, the fly-brain modes *Shadow* / *Roam* / *Off*, *Relocalize* |
| **Drive** | *Start chassis* / *Stop chassis*, *Guard reset*, posture (*Stand* / *Crouch*) |
| **Display** | map views (*Top*, *Iso*, *Follow*, *Clear trail*), map changes (*Commit changes*, *Auto commit*) |

The outline tree shows: base map, session (LiDAR), localization (fitness), chassis (posture and LiDAR
height), mission (state and reason), map changes, and solution information. The message list records
every event the server raises, including the reasons a command was refused.

### 1.10 Maps and the operator's workflow

1. **Charging lock:** the session starts locked (`XT_CHASSIS_DISABLED=1`). *Start LiDAR* streams
   the sensors and localizes; no motion until the lock is lifted with both opt-ins.
2. **Mapping:** drive a manual session to cover the building, then *Save map*. The session writes
   `runs/<id>/` with `map.ply`, `trajectory.csv`, `summary.json` and `navigation.jsonl`.
3. **Export:** `tools/export_session_map.py` builds a map package (grid, height layers, `MAP_INFO.json`).
   `tools/correct_map.py` and `correction_draft.json` record manual cleanups of obstacle changes.
4. **Navigation:** start the server with `XT_MAP=maps/<package>`; the session then continues on it.

Coverage is the main limit: a base map with large unknown areas makes relocalization fail outside
the mapped region ([docs/slam_history.md](docs/slam_history.md)).

---

## 2. The fly brain

### 2.1 Pipeline

| Step | Where | Output |
| --- | --- | --- |
| LiDAR → retina (`LidarRetinaV3`) | compute host, per scan | Hz per input cell for LC4, LPLC2, LC9, left/right |
| Input cells | GPU, registry order | the connectome receives these rates as Poisson input |
| Connectome | GPU, 10 × 10 ms blocks per window, persistent state | spike counts of 9 readout types, per anatomical side |
| Decoder (v1–v9) | service | state and intent (*v*, *w*) |
| Envelope | server | reduces or zeroes the intent; never adds motion |

Window data flow: a 100 ms window of rates and spikes; intents older than 0.35 s or computed from
scans older than 0.45 s are dropped (see [docs/architecture.md](docs/architecture.md)).

### 2.2 Readouts and decoder states

| Readout | Role in the decoder |
| --- | --- |
| DNp01 | giant fibre, escape trigger |
| DNp02, DNp04, DNp06, DNp11 | loom-responsive descending neurons |
| DNp09 | P9, forward walking |
| DNa01, DNa02 | steering; DNa02 right minus left sets the turn |
| MDN | moonwalk, backing up |

Decoder states: **FORWARD**, **EXPLORE**, **TURN_LEFT**, **TURN_RIGHT**, **HOLD**, **REST**,
**FREEZE**, **ESCAPE_PROGRAM**, **BACK_OFF**, **FLEE**. Decoder v9 (used in the latest runs) adds an
endogenous exploration drive and longer flights.

### 2.3 Brain modes

| Mode | What the brain does | Where it is used |
| --- | --- | --- |
| `off` | nothing; classical navigation only | default |
| `shadow` | runs on live scans, logs intents, sends nothing | stage 4 |
| `drive` (*Roam*) | intent → envelope → geofence / keep-in → the normal 0.3 s lease; the brain drives the robot | stage 5 |
| `reflex` | the planner drives; the brain takes over only to freeze or escape, then the task replans around a keep-out disc | stage 6 |

### 2.4 Neuron registry

`configs/fly/loom_registry.json` binds every input and readout cell by exact `cell_type`, `root_id`
and model index for FlyWire 783 (annotation TSV SHA-256 `9a4f8b2f…`). It is rebuilt with
`tools/build_registry.py` and was verified from a fresh clone (513 cells, identical). Indices are
not portable to other connectome versions.

---

## 3. Results so far

All numbers come from the recorded experiments in [`experiments/`](experiments/README.md).

* **Loom → escape on the real robot** (stage 4/5, LiDAR only): in shadow mode reactions of
  0.0–0.33 s to 9 operator approaches; in drive mode a median 0.35 s loom → escape decision
  (0.09–1.08 s, 4 of 12 episodes not triggered in `stage5_003`). Lateral looms turn the robot
  away from the stronger giant fibre (up to ~100°), frontal looms back it off. 0 contacts in every
  drive where the operator reported contacts. No left/right swap anywhere in
  LiDAR → body → retina → brain → decoder.
* **Brain timing:** 84–110 ms of GPU time per 100 ms window on a shared RTX 5090D (0.9–1.2× real
  time). On an idle GPU the reproduction measured 46 ms per window (about 2.2× real time).
* **Stage 1 reproduction:** all 629 recorded rates identical from a fresh clone
  ([docs/verification.md](docs/verification.md)).
* **Closed-loop simulation:** stage 6 (planner + fly reflexes) passed in `stage6_003`; stage 3
  formally failed on one scenario with a known evaluation flaw (person_right).
* **Open problems:** keep-in and fence overshoot while standing (several stage-5 criteria failed by
  0.05–0.2 m); reflex/planner oscillation near people; no intrinsic walking drive; the Turbo slip
  incident is not explained.
* **EEG → DNa02** (offline): 24/24 calibration conditions turned the expected way. This validates a
  direct motor-node pathway, not "the fly understands EEG".

---

## 4. Verification and simulation

* **Unit tests** (any machine): registry identity, retina, decoders, EEG encoder, envelope, synthetic
  arena. `pytest` (11 tests).
* **Blind simulation** (no GPU): `loom_sim` with a constant-forward baseline.
* **Brain in the loop** (GPU): `loom_sim … brain`, Stage 1 reproduction (`tools/repro_stage1.py`),
  the stage-3 suite (`experiments/loom_005/stage3_eval7.py`), and stage 6 (`reflex_sim` with the brain
  service).
* **Control server without a robot:** `tools/make_synthetic_raw.py` writes a LiDAR + IMU recording;
  `flyhead.server.app --replay` runs it through the server, SLAM and the brain link.
* **Console replay:** the same replay drives the operator console, including brain shadow display.

What has been re-run from a fresh clone, with the results: [docs/verification.md](docs/verification.md).
Not covered there: `robot/` on real hardware and the numbers that depend on the private recorded maps.

---

## 5. Repository layout

| Path | Role | Runs on |
| --- | --- | --- |
| [`flyhead/fly/`](flyhead/fly) | 果蝇 — connectome model, encoders (LiDAR loom, EEG), decoders, brain service | GPU host |
| [`flyhead/slam/`](flyhead/slam) | SLAM — KISS-ICP odometry, relocalization, map layers, raw recordings | compute host |
| [`flyhead/navigation/`](flyhead/navigation) | route planning, following, host stop / slow / detour chain | compute host |
| [`flyhead/server/`](flyhead/server) | 服务端 — control server: robot session over SSH, control loop, brain link | compute host |
| [`flyhead/safety/`](flyhead/safety) | command envelope (reduce or zero only) | compute host |
| [`flyhead/sim/`](flyhead/sim) | 仿真 — closed-loop simulations, synthetic arena, report | any (brain arm: GPU) |
| [`flyhead/monitor/`](flyhead/monitor) | 监视器 — operator web console + SSH tunnel | operator PC |
| [`robot/`](robot) | 机器人部署 — ROS 2 bridge (LiDAR, IMU, chassis, posture), standalone | robot (Pi 4B, ROS 2 Foxy) |
| [`experiments/`](experiments/README.md) | protocols, locked results and as-executed scripts of every stage | — |
| [`docs/`](docs) | architecture, reproduction, verification, demos, SLAM operations, navigation | — |
| `configs/`, `scripts/`, `tools/`, `tests/` | neuron registry, launchers, map tools, renderers, unit tests | — |

The modules are decoupled: the control server never loads torch (it talks to the brain service over
local TCP), the encoders and decoders are plain NumPy, and the robot bridge does not import the
package. See [docs/architecture.md](docs/architecture.md) for the module boundaries.

---

## 6. Quick start

### 6.1 Anywhere: unit tests and blind simulation

```bash
git clone https://github.com/12sqawdwq/FlyHead.git && cd FlyHead
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && pytest
python -m flyhead.sim.loom_sim person_front blind 25 runs/blind.jsonl
python -m flyhead.sim.report runs/blind.jsonl
```

### 6.2 With a CUDA GPU (≥ 16 GB free): the connectome in the loop

```bash
pip install -e ".[brain]"
python scripts/fetch_upstream.py                    # pinned fly-brain code + FlyWire v783, identity-checked
python tools/repro_stage1.py runs/repro_stage1      # stage 1: compared with the archived record
python -m flyhead.sim.loom_sim person_front brain 25 runs/brain.jsonl --decoder 9
```

### 6.3 Demo renders

```bash
pip install -e ".[demo]"
python tools/render_demo.py decision runs/decision.mp4 runs/brain.jsonl     # the decision chain
python tools/render_demo.py reflex runs/stage6.mp4 runs/planner.jsonl runs/reflex.jsonl
```

### 6.4 The robot and the control server

Full procedure: [docs/reproduce.md](docs/reproduce.md) (sections 2b and 4) and
[docs/slam_operations.md](docs/slam_operations.md). In short:

```bash
# compute host
XT_ROBOT_HOST=robot XT_ROBOT_ROOT=/home/<user>/FlyHead XT_MAP=maps/<package> bash scripts/start_server.sh
bash scripts/start_brain_service.sh live_001        # optional, for brain modes
# operator PC
XT_COMPUTE_HOST=<alias> python flyhead/monitor/preview.py
```

Physical motion requires `XT_CHASSIS_DISABLED=0 XT_REMOTE_MOTION_ENABLED=1` on the server launch,
and the bridge enforces the same two interlocks.

---

## 7. Safety

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
during any drive. Treat this as research code: the host's stop distances are commanded-speed
estimates, and the Turbo incident above is not explained.

---

## 8. Credits and licences

* Connectome model: [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) (GPL-2.0), fetched at a pinned commit, not redistributed here.
* Connectome and annotations: FlyWire (Dorkenwald et al. 2024, Schlegel et al. 2024; [flyconnectome/flywire_annotations](https://github.com/flyconnectome/flywire_annotations)).
* LiDAR odometry: [KISS-ICP](https://github.com/PRBonn/kiss-icp). Web console: [three.js](https://threejs.org) (MIT, vendored with its licence).

No licence has been chosen for FlyHead's own code yet; until one is added, all rights are reserved by the author.

**Topics:** connectome · flywire · drosophila · spiking neural network · LIF · neurorobotics · embodied AI · ROS 2 · LiDAR · looming · escape behaviour · SLAM · navigation · EEG · brain-computer interface · PyTorch · CUDA
