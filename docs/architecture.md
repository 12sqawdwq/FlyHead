# Architecture

Three machines, five processes, one direction of authority: the brain decides, every
other layer may only withhold, reduce or zero its command.

```text
operator PC                 compute host (GPU)                                      robot (Pi 4B, ROS 2 Foxy)
flyhead.monitor  ──SSH -L──► flyhead.server.app :8091 ──SSH stdio──────────────────► robot/run.sh → robot/bridge.py
 web console                  ├─ flyhead.slam   (KISS-ICP in a child process)          Unitree L1 LiDAR + IMU
 (task dispatch only)         ├─ flyhead.navigation (planner, host stop chain)          DIABLO chassis (ROS 2)
                              ├─ flyhead.safety.envelope                               link-loss return
                              └─ flyhead.server.brain_link ──TCP 127.0.0.1:8095──► flyhead.fly.service
                                   (retina on live scans)                              (connectome on CUDA)
```

## Module boundaries

| Package | Imports | Never imports |
| --- | --- | --- |
| `flyhead.fly.encoders`, `flyhead.fly.decoders` | numpy | torch, ROS, sockets |
| `flyhead.fly.model`, `engines`, `event_model` | torch, triton, upstream `run_pytorch` | server, slam |
| `flyhead.fly.service` | encoders, decoders, model (lazily) | robot I/O of any kind |
| `flyhead.safety` | numpy | anything that can move the robot |
| `flyhead.slam` | numpy, scipy, kiss-icp | fly, server |
| `flyhead.navigation` | slam.navmap, numpy, scipy, cv2 (lazily) | fly, server |
| `flyhead.server` | slam, navigation, safety, fly.encoders, aiohttp | torch (the brain is a separate process) |
| `flyhead.sim` | fly, safety, slam.navmap, navigation, server.brain_link | robot I/O |
| `flyhead.monitor` | stdlib only | the package's control code |
| `robot/` | rclpy, DIABLO / Unitree messages | `flyhead` (deployed on its own) |

All filesystem locations come from `flyhead/paths.py` (environment variables with repository
defaults); no module hardcodes a host path.

## Brain modes (`flyhead.server.brain_link`)

* `off` — classical SLAM navigation only.
* `shadow` — retina and brain run on live scans; intents are logged, never sent (stage 4).
* `drive` — intent → envelope → geofence / keep-in → the normal 0.3 s command lease (stage 5).
* `reflex` — the planner drives; the brain takes over only while it freezes or escapes, then the
  task replans around a keep-out disc (stage 6).

## Data flow per 100 ms window

1. `bridge.py` streams LiDAR frames to the server (binary frames over SSH stdout).
2. `brain_link.on_scan` keeps points 0.08–0.50 m above the floor, moves them to the body frame and
   runs `LidarRetinaV3` → `{('LC4','left'): Hz, …}`; sends the rates to the service.
3. `flyhead.fly.service` writes the rates into the input cells (registry order), runs 10 × 10 ms
   GPU blocks with persistent state, sums readout spikes per type and side, decodes an intent.
4. `brain_link.command` drops intents older than 0.35 s or computed from scans older than 0.45 s,
   applies `safety.envelope.limit`, the fence / keep-in and the localization-fitness gate.
5. The server sends the command with a ≤ 0.3 s deadline on the robot clock; the bridge zeroes
   motion when it expires.

## Neuron registry

`configs/fly/loom_registry.json` binds every input and readout cell by exact `cell_type`,
`root_id` and model index for this connectome file and ordering (FlyWire 783, annotation
TSV SHA-256 `9a4f8b2f…`, completeness CSV SHA-256 `52b0ac60…`). Rebuild it with
`tools/build_registry.py` after `scripts/fetch_upstream.py --annotations`. Indices are not
portable to other connectome versions.
