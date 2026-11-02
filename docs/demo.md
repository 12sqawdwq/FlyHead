# Demos / 演示

Three kinds of footage, always labelled; they are not interchangeable:

| Label | Meaning |
| --- | --- |
| **REAL** / 真实执行 | the physical DIABLO robot, filmed on a phone |
| **SIM** / 仿真 | simulated world and LiDAR; the brain is the full connectome on the GPU |
| **CONSOLE (replay)** / 上位机回放 | the real operator console and control server, fed a synthetic LiDAR recording; brain in shadow mode (decisions shown, never sent) |

The retina is an engineered LiDAR-to-rate mapping onto registry-bound input cells, not a
reconstruction of fly vision. Left/right in the neuron panels is the anatomical side of the cells.

---

## 1. Real robot / 真实机器人

### 1.1 Brain drive with a person approaching — stage5_004 (2026-10-10)

![REAL: stage 5 brain drive](media/preview/real_stage5_escape.gif)

Full clip (54 s, audio removed): [media/real/stage5_004_brain_drive_escape.mp4](media/real/stage5_004_brain_drive_escape.mp4)

* **What drives the robot:** the full-connectome brain (decoder V6) through the safety envelope and
  the 0.3 s command lease — no planner, no scripted path. A person walks up to the robot; looming
  in the LiDAR drives LC4 / LPLC2, the giant fibre and DNa02 respond, and the decoder issues escape
  programs (turn away, back off).
* **Which run:** the phone's recording time stamp (22:57:17, Beijing) falls inside the stage5_004
  drive window (22:53:38–22:58:03, `experiments/loom_005/runs/stage5_004/D1_start.txt`, `end.txt`).
  The clip may extend a few seconds past the end of the drive.
* **Recorded outcome of that run** (`experiments/loom_005/RESULTS.md`): 262 s drive, standing,
  0 contacts reported, 30 escape programs (15 frontal, 15 lateral), lateral turns up to 103°.
  Known defect visible in such runs: frontal reversals often lasted only 0.1–0.6 s because the
  frontal/lateral choice flip-flopped; later decoders (V7–V9) changed this.
* Supervision as in `PROTOCOL_STAGE5.md`: RC supervisor, geofence, speed limits 0.20 m/s forward,
  −0.30 m/s back, 1.0 rad/s.

### 1.2 Autonomous navigation clips (SLAM phase, before the brain modes)

These two clips show **autonomous navigation without the fly brain**: the robot drives planned
routes on a saved SLAM map (the classical layer in the README, section 1). The brain was not
involved. They were recorded before the first brain run (2026-10-10); the file timestamps are
2026-10-08, the day the navigation stack was rebuilt.

| Clip | Content |
| --- | --- |
| [media/real/hallway_posture_drive.mp4](media/real/hallway_posture_drive.mp4) (19 s) | standing / crouched posture changes and route driving in a hallway |
| [media/real/office_night_drive_4x.mp4](media/real/office_night_drive_4x.mp4) (6 min shown at 4×) | autonomous route driving through the office at night, in the environment of the SLAM maps |

Their numbers (lap times, speeds, stop distances) are in the README, section 1.8, from the same
period and the same navigation code.

---

## 2. Simulation / 仿真

### 2.1 The decision chain, window by window

![SIM: decision chain](media/preview/decision_chain.gif)

Video (25 s, every 100 ms window of the run): [media/sim/decision_chain_person_front.mp4](media/sim/decision_chain_person_front.mp4) ·
still at the escape (t = 4.3 s): [media/sim/decision_chain_escape.png](media/sim/decision_chain_escape.png)

Scenario `person_front` (stage-3 criteria): a person walks toward the robot at 0.5 m/s and stops
0.7 m away. Decoder V9. Panels and where each number comes from:

| Panel | Shows | Code / log field |
| --- | --- | --- |
| world | arena, ray-cast LiDAR returns, person, robot coloured by decoder state | `flyhead/sim/loom_sim.py` (`World.scan`), row `x, y, yaw, objects` |
| 1 | Poisson rates written into LC4 / LPLC2 / LC9 cells, per anatomical side | `flyhead/fly/encoders/lidar_loom.py` (`LidarRetinaV3`), row `inputs` |
| 2 | spike rates of the descending neurons in this 100 ms window | `flyhead/fly/model.py` (`Brain.step`), registry `configs/fly/loom_registry.json`, row `readouts` |
| 3 | decoder features (giant fibre, P9, MDN, DNa02 R−L) and the decision | `flyhead/fly/decoders/loom.py` (`DecoderV9`), row `intent` |
| 4 | decision over the whole run and the executed command after the envelope | `flyhead/safety/envelope.py`, row `executed`, `envelope`, `clearance` |

In this run the brain freezes at 3.8 s and starts an escape program at 3.9 s (LC4 / LPLC2 on both
sides, giant fibre 125 Hz): it backs off at −0.3 m/s, turns, then flees for 9.6 s (7.8–17.4 s);
0 contacts.

### 2.2 Stage 6: planner + fly reflexes

![SIM: stage 6](media/preview/stage6.gif)

Video: [media/sim/stage6_planner_vs_reflex.mp4](media/sim/stage6_planner_vs_reflex.mp4)

Same seed and person in both arms. Left: the SLAM planner drives, the brain runs in shadow.
Right: the brain takes over (red path) while it freezes or escapes, then the planner replans
around a keep-out disc. `flyhead/sim/reflex_sim.py` with the brain service over TCP
(`flyhead/fly/service.py`, `flyhead/server/brain_link.py`). Result of all three seeds:
[verification.md](verification.md) (STAGE 6 SIM PASSED).

---

## 3. Operator console / 上位机

![CONSOLE: replay with brain shadow](media/preview/console.gif)

Video (61 s): [media/console/console_replay_brain_shadow.mp4](media/console/console_replay_brain_shadow.mp4) ·
still: [media/console/console_brain_shadow.png](media/console/console_brain_shadow.png)

The unmodified console (`flyhead/monitor`) connected through its SSH tunnel to the control
server (`flyhead/server/app.py --replay`) on the GPU host, with the brain service running.

| Console element | Meaning |
| --- | --- |
| Graphics (point cloud) | the base map the session relocalized on; red arrow = robot pose, purple = driven path |
| Outline → Localization `1.00` | relocalization fitness on the base map (`flyhead/slam/reloc.py`) |
| Chassis `stand · 0.47 m` | posture detected from the LiDAR height above the map floor |
| Messages `Shared map committed … new obstacle` | the person detected as a change against the base map (`flyhead/slam/navmap.py`) |
| Fly brain `shadow · connected · TURN_LEFT v 0.14 w 0.20 · input 0.11 s` | live decoder state and the command it *would* send, input age; shadow = never sent |
| `Charging lock` banner | motion interlock on; replay has no robot link at all |

Honest limits of this clip: the LiDAR is synthetic and sparse in the 0.08–0.50 m band the retina
uses, so the brain's reaction to the walking person is weak here (LC9 drops, REST, then a turn as
the person leaves) — the escape behaviour is shown in 1.1 and 2.1.

---

## Regenerating / 复现这些素材

```bash
# simulation (logs from flyhead.sim.loom_sim / reflex_sim, see reproduce.md)
python tools/render_demo.py decision OUT.mp4 runs/person_front_brain.jsonl
python tools/render_demo.py still OUT.png runs/person_front_brain.jsonl 4.3
python tools/render_demo.py reflex OUT.mp4 runs/planner_seed1.jsonl runs/reflex_seed1.jsonl

# console replay (GPU host): recording with a person + navigation package in its SLAM frame
python tools/make_synthetic_raw.py runs/synth_person.xt --seconds 40 --person --base-out runs/console_base
python -m flyhead.server.app --replay runs/synth_person.xt --port 8091      # session once -> runs/replay_*/map.ply
bash scripts/start_brain_service.sh console_demo                              # LOOM_DECODER=9
XT_BRAIN_ENABLED=1 python -m flyhead.server.app --replay runs/synth_person.xt \
    --base runs/replay_<id>/map.ply --nav runs/console_base/nav --port 8091
# operator PC
python tools/export_preview_map.py --source <copy of runs/replay_<id>/map.ply>
python flyhead/monitor/preview.py --compute-host <alias>                     # Start LiDAR, then Mission -> Shadow
```

---

## Real-site material / 真实场地素材

Published with the site owner's consent (the map package itself stays out of the repository). The README
section "Videos" shows each item with a preview; this table gives the sources.

| Item | Source data | Renderer |
| --- | --- | --- |
| `realmap/slam_map_build.mp4` | map package `onboard_20260926_manual_cleanup_20261005`: `map.ply`, `trajectory.csv` of the 2026-09-25 mapping session | `tools/render_real.py mapbuild` |
| `realmap/slam_map_orbit.mp4` | the same `map.ply` (points below 1.3 m in the map frame) | `tools/render_real.py orbit` |
| `realmap/nav_layers.png` | `map.pgm`, height layers, `trajectory.csv`, real tour logs | `tools/render_real.py layers` |
| `realmap/real_tour_729s.mp4`, `real_tour_138s.mp4` | **real robot** console observation logs `standing_tour_observation_20261004T213408.jsonl`, `standing_tour_independent_axes_20261004T215856.jsonl` (navigator messages: pose, route, goal, state, reason, fitness, command) | `tools/render_real.py navlog` |
| `realmap/decision_<scenario>.mp4` (8) | `flyhead.sim.loom_sim <scenario> brain … --map <package> --decoder 9` on the GPU host | `tools/render_demo.py decision --map` |
| `realmap/scenarios_brain_vs_blind.png`, `decoder_states.png` | the same runs plus the blind arm | `tools/render_real.py scenarios`, `states` |
| `realmap/stage6_planner_vs_reflex.mp4` | `flyhead.sim.reflex_sim <package> planner|reflex 1` with the brain service | `tools/render_demo.py reflex --map` |
| `realmap/console/*` | the control server replaying `make_synthetic_raw.py --map <shifted package> --from-cloud --person` on `--base <shifted map.ply>`, brain service running; console recorded headless | `tools/shift_map_package.py`, `tools/make_synthetic_raw.py` |

The console replay's scans are taken from the saved cloud (occluded by the grid) along a scripted
path, with a person cylinder added; it relocalizes at fitness 1.00. A recording generated from the
grid alone does not relocalize on a real cloud (about 60 % of wall points agree), which is why the
cloud is used.
