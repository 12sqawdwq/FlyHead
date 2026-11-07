<div align="center">

<a href="https://flyhead.live/"><img src="docs/media/site/hero.gif" width="100%" alt="FlyHead interactive site: the robot is taken apart in 3D"></a>

<h3>A fruit fly's whole-brain connectome, simulated on a GPU, driving a real wheel-legged robot.</h3>

<a href="https://flyhead.live/"><img src="https://img.shields.io/badge/%E2%96%B6%20Try%20the%20interactive%203D%20demo-flyhead.live-f78166?style=for-the-badge" alt="Try the interactive 3D demo at flyhead.live"></a>

<p>
<img src="https://img.shields.io/badge/connectome-FlyWire%20v783-3fb950?style=flat-square" alt="FlyWire v783">
<img src="https://img.shields.io/badge/neurons-138%2C639%20LIF-58a6ff?style=flat-square" alt="138,639 LIF neurons">
<img src="https://img.shields.io/badge/ROS%202-Foxy-22314e?style=flat-square&logo=ros&logoColor=white" alt="ROS 2 Foxy">
<img src="https://img.shields.io/badge/status-research%20prototype-d29922?style=flat-square" alt="research prototype">
</p>

<p>
<b>English</b> · <a href="README.zh-CN.md">中文</a> ·
<a href="https://flyhead.live/">Website</a> ·
<a href="#demonstrations">Demos</a> ·
<a href="#system-overview">System</a> ·
<a href="#quick-start">Quick start</a>
</p>

<sub>Above: a 3D render captured from the website, not a photo of the robot. Real footage follows.</sub>

</div>

## The real robot, driven by the fly brain

<table>
<tr>
<td width="55%" valign="top">
<img src="docs/media/cards/real_brain.gif" width="100%" alt="the real robot escaping as a person approaches">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <sub>Phone footage · <a href="docs/media/real/stage5_004_brain_drive_escape.mp4">mp4</a></sub></p>
</td>
<td width="45%" valign="top">

**A person walks up. LiDAR looming drives identified visual neurons, the connectome responds, and a decoder reads descending neurons into motion.**

* **138,639** LIF neurons and **15,091,983** connection records (FlyWire v783)
* LiDAR looming → LC4 / LPLC2 / LC9 → descending neurons (DNp01, DNa02, MDN) → escape, turning, walking
* A safety envelope may only reduce or zero the brain's commands

</td>
</tr>
</table>

The stimulus encoders and the decoder are engineering proxies, not a reconstruction of fly vision or motor control.

## Explore it in 3D

**Each card opens that chapter on [flyhead.live](https://flyhead.live/)**: scroll to disassemble the robot, drag to rotate, switch scenarios.

<table>
<tr>
<td width="33%" valign="top">
<a href="https://flyhead.live/#p=0.15"><img src="docs/media/site/exploded.gif" width="100%" alt="exploded robot"></a>
<p><img src="https://img.shields.io/badge/3D%20RENDER-8b949e?style=flat-square" alt="3D RENDER"> <b><a href="https://flyhead.live/#p=0.15">Take it apart</a></b></p>
<p><sub>Vendor meshes plus illustrative parts; scroll to disassemble</sub></p>
</td>
<td width="33%" valign="top">
<a href="https://flyhead.live/#p=0.42"><img src="docs/media/site/site.gif" width="100%" alt="site point cloud"></a>
<p><img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> <b><a href="https://flyhead.live/#p=0.42">The mapped site</a></b></p>
<p><sub>Point cloud from a real LiDAR mapping session</sub></p>
</td>
<td width="33%" valign="top">
<a href="https://flyhead.live/#p=0.48"><img src="docs/media/cards/rviz_wall_ahead.gif" width="100%" alt="brain and blind robot"></a>
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b><a href="https://flyhead.live/#p=0.48">Brain vs. no brain</a></b></p>
<p><sub>Closed-loop simulation; selected scenarios, not an average</sub></p>
</td>
</tr>
<tr>
<td width="33%" valign="top">
<a href="https://flyhead.live/#p=0.65"><img src="docs/media/site/whole_brain.gif" width="100%" alt="fly brain neurons"></a>
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b><a href="https://flyhead.live/#p=0.65">A whole fly brain</a></b></p>
<p><sub>Real FlyWire coordinates; a sample of the neurons is drawn</sub></p>
</td>
<td width="33%" valign="top">
<a href="https://flyhead.live/#p=0.81"><img src="docs/media/site/region_to_motion.gif" width="100%" alt="brain region to motion"></a>
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b><a href="https://flyhead.live/#p=0.81">From brain region to motion</a></b></p>
<p><sub>Simulated rates, an engineering decoder; signal animation is illustrative</sub></p>
</td>
<td width="33%" valign="top">
<a href="https://flyhead.live/#p=0.915"><img src="docs/media/site/decisions.gif" width="100%" alt="decision replay"></a>
<p><img src="https://img.shields.io/badge/REAL%20LOG-3fb950?style=flat-square" alt="REAL LOG"> <b><a href="https://flyhead.live/#p=0.915">Decisions, window by window</a></b></p>
<p><sub>Real-robot brain windows; selected episodes, the person is illustrative</sub></p>
</td>
</tr>
</table>

## Two decision layers in one body

| | |
| --- | --- |
| **Autonomous navigation** | LiDAR SLAM on a saved map of the building, centreline route planning, tours, detours and a host safety chain. Works on its own, without the brain. |
| **Fly brain** | The complete FlyWire v783 *Drosophila* connectome on a GPU turns LiDAR looming into escape, turning and walking through identified descending neurons. A safety envelope may only reduce or zero its commands. |

Hardware: a DIABLO wheel-legged robot (Raspberry Pi 4B, ROS 2 Foxy, Unitree L1 LiDAR), a GPU compute host
and a Windows operator PC. *Xingtian (刑天) fights on after losing his head; here a fly brain is the head.*

---

## Demonstrations

<p>
<img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> physical robot (phone footage) &nbsp;
<img src="https://img.shields.io/badge/REAL%20LOG-3fb950?style=flat-square" alt="REAL LOG"> the robot's own logs, replayed &nbsp;
<img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> the saved SLAM map of the real building &nbsp;
<img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> simulated LiDAR, full connectome on GPU &nbsp;
<img src="https://img.shields.io/badge/CONSOLE-a371f7?style=flat-square" alt="CONSOLE"> real console and server, replayed session
</p>

### The real robot

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/nav_hallway.gif" width="400" alt="hallway">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <b>Autonomous navigation · hallway</b></p>
<p><sub>Standing / crouched posture and route driving, no fly brain · <a href="docs/media/real/hallway_posture_drive.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/nav_office.gif" width="400" alt="office at night">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <b>Autonomous navigation · office at night</b></p>
<p><sub>Route driving through the mapped office, no fly brain · 4× · <a href="docs/media/real/office_night_drive_4x.mp4">mp4</a></sub></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/real_brain.gif" width="400" alt="brain drive">
<p><img src="https://img.shields.io/badge/REAL-f78166?style=flat-square" alt="REAL"> <b>The fly brain drives</b></p>
<p><sub>A person approaches and the robot escapes · <a href="docs/media/real/stage5_004_brain_drive_escape.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/tour.gif" width="400" alt="real tour replay">
<p><img src="https://img.shields.io/badge/REAL%20LOG-3fb950?style=flat-square" alt="REAL LOG"> <b>Autonomous tour, from the robot's log</b></p>
<p><sub>Every frame is one recorded navigator message · <a href="docs/media/realmap/real_tour_729s.mp4">mp4</a> · <a href="docs/media/realmap/real_tour_138s.mp4">short tour</a></sub></p>
</td>
</tr>
</table>

### The real site: SLAM map

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/mapbuild.gif" width="400" alt="map build-up">
<p><img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> <b>The mapping session, replayed</b></p>
<p><sub>The map grows along the mapping path · <a href="docs/media/realmap/slam_map_build.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/orbit.gif" width="400" alt="3-D point cloud">
<p><img src="https://img.shields.io/badge/REAL%20SITE-d29922?style=flat-square" alt="REAL SITE"> <b>The saved point cloud in 3-D</b></p>
<p><sub>Walls and furniture, coloured by height · <a href="docs/media/realmap/slam_map_orbit.mp4">mp4</a></sub></p>
</td>
</tr>
</table>

<a href="docs/media/realmap/nav_layers.png"><img src="docs/media/realmap/nav_layers.png" width="100%" alt="navigation layers"></a>

<sub>Navigation layers of the saved map: occupancy grid · clearance field and the centreline every route follows · obstacle heights · the mapping path and real tours. Published with the site owner's consent; the map package itself is not in this repository.</sub>

### The fly brain on the real map

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/rviz_decision.gif" width="400" alt="decision chain">
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b>The decision chain, window by window</b></p>
<p><sub>A person from the left: LiDAR → LC4/LPLC2/LC9 → descending neurons → decoder → command · <a href="docs/media/rviz/person_left.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/rviz_roam.gif" width="400" alt="free roaming">
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b>Free roaming</b></p>
<p><sub>Explore, escape, flee, freeze and hold in one run · <a href="docs/media/rviz/roam_open.mp4">mp4</a></sub></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/media/cards/rviz_stage6.gif" width="400" alt="planner and reflexes">
<p><img src="https://img.shields.io/badge/SIM-58a6ff?style=flat-square" alt="SIM"> <b>Planner with fly reflexes</b></p>
<p><sub>The planner drives to a goal; the brain takes over when something looms · <a href="docs/media/rviz/stage6.mp4">mp4</a></sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/media/cards/console.gif" width="400" alt="operator console">
<p><img src="https://img.shields.io/badge/CONSOLE-a371f7?style=flat-square" alt="CONSOLE"> <b>Operator console on the real map</b></p>
<p><sub>Relocalization, brain in shadow mode, charging lock on · <a href="docs/media/realmap/console/console_real_map_brain_shadow.mp4">mp4</a></sub></p>
</td>
</tr>
</table>

More scenarios: [person front](docs/media/rviz/person_front.mp4) · [person right](docs/media/rviz/person_right.mp4) ·
[wall ahead](docs/media/rviz/wall_ahead.mp4) · [loom front](docs/media/rviz/loom_front.mp4) ·
[loom left](docs/media/rviz/loom_left.mp4) · [loom right](docs/media/rviz/loom_right.mp4).
The simulation clips are RViz2 replays of recorded 100 ms windows ([tools/rviz_replay](tools/rviz_replay)); no robot is connected.

### The operator console

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

---

## System overview

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#EEF2FF', 'primaryBorderColor': '#2148B8', 'primaryTextColor': '#1F2328', 'lineColor': '#57606A', 'clusterBkg': '#FAFAF7', 'clusterBorder': '#D0D7DE', 'edgeLabelBackground': '#FFFFFF'}}}%%
flowchart TB
    subgraph BOT["Robot · Raspberry Pi 4B, ROS 2 Foxy"]
        direction LR
        SENS(["Unitree L1 LiDAR + IMU"]) --> BR["robot/bridge.py"] --> CH(["DIABLO chassis"])
    end
    subgraph HOST["Compute host · GPU"]
        direction TB
        subgraph SRV["Control server · flyhead.server.app"]
            direction LR
            SLAM("<b>SLAM</b><br/>KISS-ICP · relocalization") --> NAV("<b>Navigation</b><br/>centreline planner · pursuit<br/>host safety chain")
            SLAM --> LINK("<b>Brain link</b><br/>LiDAR looming encoder")
            ENV("<b>Safety envelope</b><br/>reduce or zero only") --> CTRL("<b>Control loop · 10 Hz</b><br/>planner or brain command")
            NAV --> CTRL
        end
        subgraph SVC["Brain service · flyhead.fly.service"]
            direction LR
            CON[["<b>Connectome</b><br/>138,639 LIF neurons"]] --> DEC("<b>Decoder</b>")
        end
    end
    subgraph PC["Operator PC"]
        UI("<b>Web console</b><br/>flyhead.monitor")
    end
    BR -->|"LiDAR frames"| SLAM
    LINK -->|"input rates"| CON
    DEC -->|"state and intent"| ENV
    CTRL ==>|"leased command"| BR
    UI <-.->|"WebSocket"| CTRL

    classDef robot fill:#FFF4EC,stroke:#C65F38,stroke-width:1.5px,color:#1F2328
    classDef server fill:#EEF2FF,stroke:#2148B8,stroke-width:1.5px,color:#1F2328
    classDef brain fill:#EAF6EF,stroke:#008A4B,stroke-width:1.5px,color:#1F2328
    classDef pc fill:#F3F3F1,stroke:#30343A,stroke-width:1.5px,color:#1F2328
    classDef key fill:#2148B8,stroke:#173AE3,stroke-width:2px,color:#FFFFFF
    class SENS,BR,CH robot
    class SLAM,NAV,LINK,ENV server
    class CTRL key
    class CON,DEC brain
    class UI pc
    style BOT fill:#FFFBF7,stroke:#C65F38,stroke-dasharray:4 3
    style HOST fill:#FAFAF7,stroke:#8C959F
    style SRV fill:#F7F9FF,stroke:#2148B8,stroke-dasharray:4 3
    style SVC fill:#F5FBF7,stroke:#008A4B,stroke-dasharray:4 3
    style PC fill:#FAFAF9,stroke:#30343A,stroke-dasharray:4 3
```

The connectome model is the FlyWire v783 LIF model from [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain)
with unmodified equations and no learning. Neurons are bound by exact `cell_type` → `root_id` → model index
([`configs/fly/loom_registry.json`](configs/fly/loom_registry.json)). Navigation is classical SLAM and planning and
does not depend on the brain. Module boundaries: [docs/architecture.md](docs/architecture.md).

---

## Repository layout

| Path | Role | Runs on |
| --- | --- | --- |
| [`flyhead/fly/`](flyhead/fly) | connectome model, encoders, decoders, brain service | GPU host |
| [`flyhead/slam/`](flyhead/slam) | KISS-ICP odometry, relocalization, map layers | compute host |
| [`flyhead/navigation/`](flyhead/navigation) | route planning, following, host stop / slow / detour chain | compute host |
| [`flyhead/server/`](flyhead/server) | control server, robot session, control loop, brain link | compute host |
| [`flyhead/safety/`](flyhead/safety) | command envelope (reduce or zero only) | compute host |
| [`flyhead/sim/`](flyhead/sim) | closed-loop simulations, synthetic arena, report | any (brain arm: GPU) |
| [`flyhead/monitor/`](flyhead/monitor) | operator web console | operator PC |
| [`robot/`](robot) | ROS 2 bridge (LiDAR, IMU, chassis, posture), standalone | robot |
| `configs/`, `scripts/`, `tools/`, `tests/` | neuron registry, launchers, map tools, renderers, unit tests | — |

---

## Quick start

Unit tests and a simulation without the brain, on any machine:

```bash
git clone https://github.com/12sqawdwq/FlyHead.git && cd FlyHead
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && pytest
python -m flyhead.sim.loom_sim person_front blind 25 runs/blind.jsonl
python -m flyhead.sim.report runs/blind.jsonl
```

With a CUDA GPU (≥ 16 GB free), the connectome in the loop:

```bash
pip install -e ".[brain]"
python scripts/fetch_upstream.py                    # pinned fly-brain code + FlyWire v783, identity-checked
python -m flyhead.sim.loom_sim person_front brain 25 runs/brain.jsonl --decoder 9
```

The robot, the control server and the console: [docs/reproduce.md](docs/reproduce.md) and
[docs/slam_operations.md](docs/slam_operations.md).

## Safety

Physical motion needs two explicit opt-ins on both the compute host and the robot
(`XT_CHASSIS_DISABLED=0`, `XT_REMOTE_MOTION_ENABLED=1`); the default is a charging lock. Every velocity
command carries a deadline of at most 0.3 s on the robot clock, the bridge zeroes motion after 2 s without
server traffic, and the brain's commands pass a safety envelope that can only reduce or zero them. An RC
supervisor is expected during any drive. This is research code, not a product.

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | machines, processes, module boundaries, data flow per window |
| [docs/reproduce.md](docs/reproduce.md) | from unit tests to the real robot |
| [docs/control_arbitration.md](docs/control_arbitration.md) | one motion source at a time, preemption, consoles |
| [docs/slam_operations.md](docs/slam_operations.md) | hosts, interlocks, interfaces, map packages, troubleshooting |
| [tools/rviz_replay](tools/rviz_replay) | replaying recorded simulations in RViz2 |

## Credits and licences

* Connectome model: [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) (GPL-2.0), fetched at a pinned commit, not redistributed here.
* Connectome and annotations: FlyWire (Dorkenwald et al. 2024, Schlegel et al. 2024; [flyconnectome/flywire_annotations](https://github.com/flyconnectome/flywire_annotations)).
* LiDAR odometry: [KISS-ICP](https://github.com/PRBonn/kiss-icp). Web console: [three.js](https://threejs.org) (MIT, vendored with its licence). Robot meshes: [DDTRobot/diablo_ros2](https://github.com/DDTRobot/diablo_ros2) (Apache-2.0).

No licence has been chosen for FlyHead's own code yet; until one is added, all rights are reserved by the author.

---

<div align="center">

**[See it in 3D at flyhead.live →](https://flyhead.live/)**

</div>
