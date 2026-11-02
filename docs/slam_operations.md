# Operations

## Hosts and locations

| Role | Host | Location |
| --- | --- | --- |
| Compute server | `compute` (SSH alias from the PC, `XT_COMPUTE_HOST`) | a FlyHead checkout (`flyhead/`, `scripts/`, `tools/`, `maps/`, `runs/`, `logs/`, `.venv`) |
| Robot | robot SSH alias on the compute server (`XT_ROBOT_HOST`; restricted key, no PTY) | a FlyHead checkout at `XT_ROBOT_ROOT` (only `robot/` and `logs/` are used) |
| Operator PC | Windows | this repository; console logs in `logs/monitor.log` |

The robot is reached from the compute server, not from the PC. The PC reaches
the robot only through the compute server (`ssh compute 'ssh <robot-ssh-alias> bash -s' < script.sh`).

The compute service listens on `127.0.0.1:8091` (tmux session `flyhead-server`,
log `logs/control_server.log`). The console serves the UI on `127.0.0.1:18101`
and tunnels `127.0.0.1:18102` to the server API.

## Starting and stopping

* **Compute service:** `bash scripts/start_server.sh` on the compute server. It
  refuses to start a second tmux session. Environment overrides: `XT_ROBOT_HOST`,
  `XT_ROBOT_ROOT`, `XT_API_PORT`, `XT_MAP` (map package directory), `XT_PYTHON`,
  `XT_TMUX_SESSION`. Stop it by ending the session in the console first, then
  `tmux send-keys -t flyhead-server C-c`.
* **Robot bridge:** never started by hand. *Start LiDAR* in the console makes the
  server run `robot/run.sh` over SSH; *End session* stops it. `run.sh` holds an
  exclusive lock (`.bridge.lock`); a second bridge exits with code 73.
* **Console:** `flyhead/monitor/start_console.pyw` (double-click) or `python flyhead/monitor/preview.py`.
  Repeated launches reuse the running console. Closing it never stops the robot or a task.

## Safety interlocks and timeouts

| Mechanism | Where | Behaviour |
| --- | --- | --- |
| `XT_CHASSIS_DISABLED` (default `1`) | server and bridge | `1` = charging lock: no chassis start, posture, guard reset or motion publishing |
| `XT_REMOTE_MOTION_ENABLED` (default `0`) | server and bridge | motion additionally needs this explicit opt-in |
| Command lease | server → bridge | every velocity has an absolute deadline ≤ 0.3 s on the robot clock; receipt never extends it |
| Clock anchor | `flyhead/server/remote_clock.py` | ping/echo with RTT ≤ 0.2 s, anchor age ≤ 1 s, 2 ms/s drift margin; without an anchor only zero commands go out |
| Keepalive | bridge | no server traffic for 2 s zeroes motion |
| Link-loss return | bridge | after 10 s of silence the applied-command trace is replayed backwards (≤ 0.20 m/s, ≤ 0.30 rad/s, ≤ 60 m / 360 s); the robot is released 30 s after the return |
| LiDAR watchdog | bridge | no scan for 5 s (25 s at start) zeroes motion and restarts the LiDAR node, at most 4 times |
| Freshness | navigator | pose or obstacle layer older than 3 s holds the task; 5 fresh qualified frames resume it |
| Localization | navigator | fitness < 0.6 for 1 s cancels the task (an occlusion within 1 m may wait 20 s) |
| Host stop chain | navigator | obstacle in front ≤ 0.35 m stops, < 0.70 m slows; then local detour; then reverse-and-wait recovery |
| Battery | server | < 25 % warns; < 15 % stops navigation, crouches and refuses new tasks |
| Idle | server | standing idle 60 s → crouch (motor heat) |
| Recording | server | 16 MiB queue, 8 GiB free-disk reserve (`--record-reserve-mib`); overflow or write failure latches a fault and inhibits motion |

The chassis driver (`diablo_ctrl` on the robot, not in this repository) runs its
LiDAR guard in report-only mode (`obstacle_enforce=false`): it publishes
`nearest_m`, `present`, `latched` and the applied command, and enforces nothing.

## Interfaces

* **Bridge stdout** frames `b'XT' | kind u8 | length u32 | payload`: 1 cloud, 2 IMU,
  3 JSON status/event, 4 JPEG. **Bridge stdin**: JSON operations, see the header of
  `robot/bridge.py`.
* **raw.xt** = every received frame prefixed with the f64 receive time
  (`flyhead/slam/rawlog.py`). It records what reached the server, not every ROS message.
* **`/ws`** (JSON): server sends `hello`, `status` (0.3 s), `nav`, `event`, `pong`;
  the console sends `t` = `session`, `chassis`, `camera`, `cmd`, `stop_motion`,
  `posture`, `safety_reset`, `goal`, `nav`, `nav_params`, `tour`, `explore`,
  `go_home`, `relocalize`, `reset_runtime`, `retrace`, `cloud_submit`,
  `auto_submit`, `save`, `ping`.
* **`/stream`** (binary): `0x06` frame reset, `0x01` + 4×4 float32 body pose.
  **`/camera`**: `0x05` + f64 stamp + JPEG.
* **`/diagnostics`** (HTTP GET, read-only): status, background tasks, transport
  contract, navigation summary. `tools/auto_tour.py` polls it.
* **`/download/<name>`**: `map.ply`, `map_topdown.pgm`, `trajectory.csv`,
  `summary.json` of the current run.

## Session outputs (`runs/<id>/`)

`raw.xt` and `raw.recording.json` (completeness record), `navigation.jsonl`
(one control record per 0.1 s cycle, events, clock anchors), `BASE.json`,
`cloud_map/` (committed map changes), `relocalization/` (recovery attempts),
and at the end `map.ply`, `trajectory.csv`, `map_topdown.pgm/json`, `summary.json`.

## Maps

All maps share the frame `xt_map`: the gravity-levelled L1 LiDAR frame at the
start of `live_20260925T204520`, z up, z = 0 at that LiDAR height (about 0.2 m
above the floor). Body yaw = LiDAR yaw + 180° (the LiDAR is mounted backwards).

A map package holds `map.ply` (localization cloud), `map.pgm` + `map.yaml`
(0.05 m grid: 0 occupied, 254 free, 205 unknown), `floor.npy`, `obst_hmin.npy`,
`obst_hmax.npy`, `obst_bins.npy` (16 height bins of 0.15 m from 0.08 m above the
floor), `trajectory.csv` and `MAP_INFO.json`.

| Package | Use |
| --- | --- |
| `onboard_20260926_manual_cleanup_20261005` | **active** base and navigation map (550,975 points) |
| `nav_20260925_03_manual_cleanup_20261005` | full-resolution corrected map (2.33 M points), source of the active package's grid and layers |
| `supplemented_20261006` (compute server only) | active package with a denser cloud merged from nine sessions; prepared, never activated |

The editor drafts and correction records inside the two corrected packages are
identity-bound by SHA-256 and kept byte-identical.

Workflows:

1. **New map:** record a session, then build a package from the run directory with
   `tools/export_session_map.py --session runs/<id> --out maps/<name> --reference <package>`.
   It keeps only a posture-consistent floor reference. A trajectory that mixes
   standing and crouching otherwise shrinks the known area. Use `--ply` to swap
   only the localization cloud of a copy of the reference package.
2. **Remove artifacts:** open `map-editor.html` in the console, outline regions,
   export the JSON draft, then `python tools/correct_map.py --draft D --source PKG
   --display flyhead/monitor/web/navigation --output NEW_PKG`.
3. **Activate a map:** set `XT_MAP` (or edit `scripts/start_server.sh`), restart the
   compute service, and regenerate the console asset with
   `python tools/export_preview_map.py --source <package>/map.ply`.

## Deploying changes

Deploy `server/`, `robot/` and `tools/` together, because the protocol and the
interlocks span both hosts:

1. In the console, stop navigation, crouch, stop the chassis and end the session;
   check `/diagnostics` shows `session_running: false`.
2. Copy `server/` and `tools/` to the compute server deployment and
   `robot/bridge.py`, `robot/transport.py`, `robot/run.sh` and `robot/camera/` to
   the robot (LF line endings; `.gitattributes` enforces them).
3. Restart the compute service with `scripts/start_server.sh`.

## Troubleshooting

* **Chassis driver exits with code 0 right after start:** the remote controller
  (or a just-exited driver) still holds SDK control authority. The server
  retries once after 3 s; otherwise hand control to the SDK on the remote controller.
* **Driver publishes telemetry but the robot does not move**
  (`command_forward` stays 0): the SDK did not grant control; power-cycle the robot.
* **Crouch request accepted but nothing happens:** the driver repeats the last
  movement frame every 50 ms, so frames must carry `up=0` after a crouch
  (the bridge does this).
* **Posture results:** the SDK can log result 255 even when standing succeeded.
  Only chassis feedback (`robot_mode` 3 stand / 2 crouch) confirms a posture.
* **Guard JSON:** an infinite distance serialized as `inf` is not valid JSON and
  made the bridge drop every guard report. Driver JSON must publish `null` instead.
  If the driver ever reports sector distances again, note that its front/rear are
  the LiDAR's, which is the body's rear/front.
* **SLAM stalls on the Pi or another small host:** keep BLAS/OpenMP single-threaded.
  The server sets `OPENBLAS_NUM_THREADS=1` itself; multithreaded OpenBLAS deadlocked here.
* **Scripts over SSH:** `pkill -f`/`pgrep -f` in an SSH one-liner matches the
  one-liner itself. Shell scripts written from Windows must keep LF endings.
* **Relocalization does not attach:** drive 1–3 m slowly toward mapped structure;
  it needs a clear margin over the second-best candidate. Areas outside the
  mapped region cannot attach.
* **Standing speed:** standing, the robot moves 2–3× the commanded speed and
  coasts about 0.25 m.
