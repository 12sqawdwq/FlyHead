# Experiments

Each directory is the record of one executed experiment, kept **as executed**: protocol,
protocol locks, results, logs and the exact scripts that ran. Executed runs were never re-run
in place; changes went into numbered amendments and new run directories.

The scripts here are snapshots that import each other by file name and refer to the original
server layout. The maintained code is in [`flyhead/`](../flyhead); the mapping is in the table
below. To re-run an experiment with current code, use the `flyhead` entry points listed in
[docs/reproduce.md](../docs/reproduce.md).

| Directory | Date | What | Outcome |
| --- | --- | --- | --- |
| [`visual_neural_001`](visual_neural_001) | 2026-09-22 | synthetic HS motion → full connectome → turn readout (shadow) | turning shadow chain works; forward readout zero |
| [`photo_startup_002`](photo_startup_002) | 2026-09-23 | 2 public photos × 25 conditions × 3 seeds; LC9 recruits P9 (forward) | 75 trials; startup branch weakens right turns |
| [`event_optimization_003`](event_optimization_003) | 2026-09-23 | event-driven propagation + CUDA Graph on the complete graph | 223 → 46–48 ms per 100 ms; spike counts identical to upstream |
| [`video_004`](video_004) | 2026-09-23 | continuous TUM RGB video, persistent state, 16 episodes / 1440 windows | LC9 input saturated; 100 ms budget not met on a shared GPU |
| [`loom_005`](loom_005) | 2026-10-10/11 | LiDAR loom retina → escape / avoidance; simulation, shadow and physical drives | see below |
| [`eeg_dna02`](eeg_dna02) | 2026-10-13 | EEG left/right probabilities → DNa02 stimulus → decoder V4 (offline) | 24/24 calibration directions; 25/33 accepted replays matched the true label |

## loom_005 stages

`PLAN.md` defines the stages and gates; `PROTOCOL_STAGE*.md` the locked criteria per stage and
amendment; `RESULTS.md` the outcome of every run; `protocol_lock_*.sha256` the file hashes locked
before each run; `runs/*/` the per-run summaries.

| Stage | Where | Result |
| --- | --- | --- |
| 0 contracts | registry | PASS |
| 1 dose response | GPU | PASS (budget: 0.9× real time) |
| 2 offline replay | recorded lap | retina v1 FAIL, v3 PASS |
| 3 closed-loop simulation | sim | formally FAILED (person_right: known evaluation flaw), other scenarios pass in later decoders |
| 4 shadow on the robot | robot, no commands | 4_001 fault (kept), 4_002 PASS |
| 5 brain drive | robot | 0 contacts reported; fence / keep-in overshoot criteria failed in several runs |
| 6 planner + reflexes | sim | 6_001, 6_002 FAILED; **6_003 PASSED** (all checks, see `runs/stage6_003/STAGE6_RESULT.json`) |

`RESULTS.md` ends at `stage6_002`; the passing `stage6_003` is recorded only in its run directory
(`runs/stage6_003/EVAL.txt`, `STAGE6_RESULT.json`) and in `PROTOCOL_STAGE6.md` (amendment 2).

| As executed (`loom_005/`) | Maintained (`flyhead/`) |
| --- | --- |
| `brain.py` | `flyhead/fly/model.py` |
| `brain_service.py`, `start_brain_service.sh` | `flyhead/fly/service.py`, `scripts/start_brain_service.sh` |
| `retina.py` | `flyhead/fly/encoders/lidar_loom.py` |
| `decoder.py` | `flyhead/fly/decoders/loom.py` |
| `envelope.py` | `flyhead/safety/envelope.py` |
| `sim_brain.py`, `sim_reflex.py`, `sim_report.py` | `flyhead/sim/loom_sim.py`, `reflex_sim.py`, `report.py` |
| (server) `brain_link.py`, `nav.py`, `server.py` | `flyhead/server/brain_link.py`, `flyhead/navigation/nav.py`, `flyhead/server/app.py` |

## What is left out

* Raw recordings (`raw.xt`, per-window `jsonl`), NumPy arrays (`*.npy`, `*.npz`), the connectome
  data and model environments: too large, regenerable, or site data.
* Map packages (floor plans of a private building).
* `video_004/VIDEO_RESPONSE.html` (3.6 MB viewer) and third-party pages copied as evidence.
* `email/` drafts and host-network records.
* `eeg_dna02/live-console/` is kept for reference but depends on robot-side modules
  (`policy`, `services`, `robot`, `map_archive`) that were not archived; it does not run as is.
  The EEG replay also needs TCFormer predictions that are not part of this repository.

Host paths in these records were replaced by placeholders (`<SERVER_ROOT>`, `<SERVER_HOME>`,
`<ROBOT_HOME>`, `<robot-ssh-alias>`). The file hashes inside the locks are unaffected, but each
lock file's own SHA-256 (quoted in some RESULTS files) refers to the original, unredacted bytes.
