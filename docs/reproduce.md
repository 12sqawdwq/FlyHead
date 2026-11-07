# Reproducing FlyHead

Four levels, each needing more hardware. Levels 1–2 need neither a GPU nor a robot.

## 1. Unit tests (any machine, Python ≥ 3.10)

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Covers the neuron registry identity, the LiDAR retina (still scene vs. approach, field side),
the decoders, the EEG encoder, the safety envelope (never adds motion) and the synthetic arena.

## 2. Closed-loop simulation without the brain

```bash
pip install -e ".[server]"
python -m flyhead.sim.loom_sim person_front blind 25 runs/blind.jsonl
python -m flyhead.sim.report runs/blind.jsonl
```

Scenarios: `wall_ahead`, `roam_open`, `loom_front|left|right`, `person_front|left|right`.
The `loom_*` objects move at 0.6 m/s and never stop, so they run into the robot
whatever it does; in `person_*` the person stops 0.7 m away.
Without `--map` a synthetic arena is generated (`flyhead.sim.synthetic_map`); the demo clips were
rendered on a recorded map that is not part of this repository, so expect the same pipeline
behaviour, not the same numbers.

## 2b. Control server and SLAM without a robot

```bash
python tools/make_synthetic_raw.py runs/synth_raw.xt --seconds 25   # LiDAR + IMU recording in the arena
python -m flyhead.server.app --replay runs/synth_raw.xt --port 8091
```

Open the console (or send `{"t": "session", "on": true}` on `ws://127.0.0.1:8091/ws`) to replay it
through the server, KISS-ICP SLAM and the map writer; `/diagnostics` reports background errors.

In replay, recorded times are mapped onto the replay clock, so with `XT_BRAIN_ENABLED=1`, a running
brain service, a base map and a navigation package the console's **Mission → Shadow** shows live
brain decisions (never sent: replay has no robot link).

## 3. Connectome in the loop (CUDA GPU)

Tested on an RTX 5090D (sm_120) with Python 3.11, torch 2.x, CUDA 13; the full graph needs about
12 GiB of GPU memory and 24 GiB of host memory while loading.

```bash
pip install -e ".[brain,server]"
python scripts/fetch_upstream.py                  # ~105 MB: fly-brain code at a pinned commit + FlyWire v783 data
python -m flyhead.sim.loom_sim person_front brain 25 runs/brain.jsonl --decoder 9
python -m flyhead.sim.report runs/brain.jsonl
```

The first run builds the weight cache in `cache/` (`FLYHEAD_CACHE_DIR`). Reflex simulation
(planner + brain) needs the brain service running:

```bash
bash scripts/start_brain_service.sh sim_service           # tmux; LOOM_DECODER=9 for the latest decoder
XT_BRAIN_ENABLED=1 python -m flyhead.sim.reflex_sim synthetic reflex 1 runs/reflex_1.jsonl
```

## 4. The real robot

Hardware: DIABLO wheel-legged robot with a Raspberry Pi 4B (ROS 2 Foxy, DIABLO SDK
`diablo_ctrl`, Unitree L1 LiDAR SDK, optional Orbbec camera); a compute host with an NVIDIA GPU;
an operator PC. Hosts reach each other over SSH (any VPN or LAN).

1. **Robot**: clone this repository (only `robot/` is used). Install paths of the ROS
   workspaces and SDK nodes are overridable: `XT_ROS_WS`, `XT_DIABLO_WS`, `XT_LIDAR_EXE`,
   `XT_CHASSIS_EXE`, `XT_CAMERA_EXE`.
2. **Compute host**: clone, create `.venv` with `.[server]` and, for the brain, `.venv-brain`
   with `.[brain]` (or set `FLYHEAD_BRAIN_PYTHON`). Add the robot as an SSH alias with a
   restricted key; `StrictHostKeyChecking=yes` is enforced.
3. **Map**: record a manual session, then build a map package (`tools/export_session_map.py`,
   see [slam_operations.md](slam_operations.md)).
4. Start the services (charging lock on by default):

   ```bash
   XT_ROBOT_HOST=robot XT_ROBOT_ROOT=/home/<user>/FlyHead XT_MAP=maps/<package> bash scripts/start_server.sh
   bash scripts/start_brain_service.sh live_001        # optional, for brain modes
   ```

5. **Operator PC**: `XT_COMPUTE_HOST=<alias> python flyhead/monitor/preview.py` and open the URL it prints.

Physical motion requires `XT_CHASSIS_DISABLED=0 XT_REMOTE_MOTION_ENABLED=1` on the server
launch; the bridge enforces the same two interlocks. Use an RC supervisor, a cleared area and
short sessions, and raise speeds step by step.
