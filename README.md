# FlyHead

**A whole-brain fruit-fly connectome as the head of a wheel-legged robot.**

FlyHead runs the complete FlyWire v783 *Drosophila* connectome (138,639 neurons,
15,091,983 connection records, leaky integrate-and-fire, PyTorch/CUDA) as the
decision maker of a real DIABLO wheel-legged robot over ROS 2. LiDAR looming is
encoded into identified visual projection neurons (LC4, LPLC2, LC9); the robot's
motion is decoded from descending neurons (giant fibre DNp01, DNa02, DNp09, MDN)
and only passes to the wheels through a safety envelope that can reduce or zero a
command, never add one.

[中文说明](README.zh-CN.md)

```text
LiDAR scan ─► virtual retina ─► LC4 / LPLC2 / LC9 ─► connectome (138k LIF) ─► DNp01 · DNa02 · DNp09 · MDN
 (robot)       (loom proxy)        (Hz per cell)        GPU, 100 ms windows         (spike counts)
                                                                                         │
robot ◄── 0.3 s command lease ◄── safety envelope ◄── fence / keep-in ◄── decoder (escape, turn, walk)
```

*Mythology note: Xingtian (刑天) fights on after losing his head. Here a fly brain is the head.*

## What it is and what it is not

| Layer | It is | It is not |
| --- | --- | --- |
| Connectome model | FlyWire v783 LIF model from [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) at a pinned commit, unmodified equations | a calibrated fly; no learning |
| Stimulus encoders | engineering proxies: angular expansion from LiDAR → LC4/LPLC2, free space ahead → LC9 | retinal or visual reconstruction |
| Neuron identity | exact `cell_type` → `root_id` → model index, annotation SHA-locked | synonym unions across named types |
| Decoder | fixed formulas on descending-neuron rates (escape program, turn, walk) | a navigation script or a constant drive |
| Execution | intent after the safety envelope, geofence and keep-in | planner output passed off as neural |

Anatomical side, LiDAR field side and robot yaw sign are kept as three separate
tables; the registry marks the field→eye assignment and the yaw sign as **not
calibrated**.

## Results so far

All numbers come from the recorded experiments in [`experiments/`](experiments/README.md).

* **Loom → escape on the real robot** (stage 4/5, LiDAR only): in shadow mode reactions of
  0.0–0.33 s to 9 operator approaches; in drive mode a median 0.35 s loom → escape decision
  (0.09–1.08 s, 4 of 12 episodes not triggered in `stage5_003`). Lateral looms turn the robot
  away from the stronger giant fibre (up to ~100°), frontal looms back it off. 0 contacts in
  every drive where the operator reported contacts. No left/right swap anywhere in
  LiDAR → body → retina → brain → decoder.
* **Brain timing**: 84–110 ms of GPU time per 100 ms window on a shared RTX 5090D
  (0.9–1.2× real time).
* **Closed-loop simulation**: stage 6 (planner + fly reflexes) passed in `stage6_003`;
  stage 3 formally failed on one scenario with a known evaluation flaw.
* **Open problems**: keep-in / fence overshoot while standing (several stage-5 criteria
  failed by 0.05–0.2 m), reflex/planner oscillation near people, no intrinsic walking drive.
* **EEG → DNa02** (offline): 24/24 calibration conditions turned the expected way; this
  validates a direct motor-node pathway, not "the fly understands EEG".

## Repository layout

| Path | Role | Runs on |
| --- | --- | --- |
| [`flyhead/fly/`](flyhead/fly) | 果蝇 — connectome model, encoders (LiDAR loom, EEG), decoders, brain service | GPU host |
| [`flyhead/slam/`](flyhead/slam) | SLAM — KISS-ICP odometry, relocalization, map layers, raw recordings | compute host |
| [`flyhead/navigation/`](flyhead/navigation) | route planning, following, host stop/slow/detour chain | compute host |
| [`flyhead/server/`](flyhead/server) | 服务端 — control server: robot session over SSH, control loop, brain link | compute host |
| [`flyhead/safety/`](flyhead/safety) | command envelope (reduce or zero only) | compute host |
| [`flyhead/sim/`](flyhead/sim) | 仿真 — closed-loop simulations, synthetic arena | any (brain arm: GPU) |
| [`flyhead/monitor/`](flyhead/monitor) | 监视器 — operator web console + SSH tunnel | operator PC |
| [`robot/`](robot) | 机器人部署 — ROS 2 bridge (LiDAR, IMU, chassis, posture), standalone | robot (Pi 4B, ROS 2 Foxy) |
| [`experiments/`](experiments/README.md) | protocols, locked results and as-executed scripts of every stage | — |
| [`docs/`](docs) | architecture, reproduction, SLAM operations, navigation method | — |
| `configs/`, `scripts/`, `tools/`, `tests/` | neuron registry, launchers, map tools, unit tests | — |

The modules are decoupled: the control server never loads torch (it talks to the brain
service over local TCP), the encoders/decoders are plain NumPy, and the robot bridge does
not import the package. See [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
git clone https://github.com/12sqawdwq/FlyHead.git && cd FlyHead
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" && pytest                 # encoders, decoders, envelope, synthetic map
python -m flyhead.sim.loom_sim loom_front blind 15 runs/blind.jsonl && python -m flyhead.sim.report runs/blind.jsonl
```

With a CUDA GPU (≥ 16 GB free), run the connectome in the loop:

```bash
pip install -e ".[brain]"
python scripts/fetch_upstream.py                  # pinned fly-brain code + FlyWire v783 data, identity-checked
python -m flyhead.sim.loom_sim loom_front brain 15 runs/brain.jsonl --decoder 9
```

Full instructions, including the robot and the control server: [docs/reproduce.md](docs/reproduce.md).

## Safety

Physical motion needs two explicit opt-ins on both the compute host and the robot
(`XT_CHASSIS_DISABLED=0`, `XT_REMOTE_MOTION_ENABLED=1`); the default is a charging lock.
Commands expire after 0.3 s, the speed ceiling defaults to 0.30 m/s, and an RC
supervisor is expected during any drive. Treat this as research code.

## Credits and licences

* Connectome model: [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) (GPL-2.0), fetched at a pinned commit, not redistributed here.
* Connectome and annotations: FlyWire (Dorkenwald et al. 2024, Schlegel et al. 2024; [flyconnectome/flywire_annotations](https://github.com/flyconnectome/flywire_annotations)).
* LiDAR odometry: [KISS-ICP](https://github.com/PRBonn/kiss-icp). Web console: [three.js](https://threejs.org) (MIT, vendored with its licence).

No licence has been chosen for FlyHead's own code yet; until one is added, all rights are reserved by the author.

**Topics:** connectome · flywire · drosophila · spiking neural network · LIF · neurorobotics · embodied AI · ROS 2 · LiDAR · looming · escape behaviour · SLAM · EEG · brain-computer interface · PyTorch · CUDA
