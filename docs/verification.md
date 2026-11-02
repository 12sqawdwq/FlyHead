# Verification record (2026-11-02)

A fresh clone of this repository (commit 45f9b92 plus the fixes in the commit that added this file)
was run on the reference GPU host (RTX 5090 D, 24 GiB, torch 2.12 + CUDA 13.0, Python 3.11),
in a new directory and venv. No robot was connected and no motion command was sent.

| Check | How | Result |
| --- | --- | --- |
| Upstream data identity | `scripts/fetch_upstream.py --annotations` | all files match the pinned size and git-blob SHA-1 |
| Neuron registry | `tools/build_registry.py` from the annotation TSV, compared with `configs/fly/loom_registry.json` | 513 cells, identical (type, root_id, model index, side) |
| Unit tests | `pytest` (also in a clean venv with only `.[dev]`) | 11 passed |
| Connectome, stage 1 | `tools/repro_stage1.py` vs. `experiments/loom_005/runs/stage1_001` | 629 / 629 values identical; 46 ms per 100 ms window on an idle GPU |
| Refactor equivalence | as-executed `loom_005/sim_brain.py` (paths patched only) vs. `flyhead.sim.loom_sim`, same arena, 3 scenarios x decoders V4 / V9 | 366 / 366 windows identical except timing fields |
| Stage 3 suite, decoder V9 | 5 scenarios, brain + blind, synthetic arena, `experiments/loom_005/stage3_eval7.py` | 0 contacts in all 10 runs; C1, C2 PASS; C3 person_* scored FAIL (see below) |
| Control server + SLAM | `tools/make_synthetic_raw.py` -> `flyhead.server.app --replay` | 77 frames, all IMU-deskewed and levelled, map saved, no background errors |
| Stage 6, planner + reflexes | brain service (`scripts/start_brain_service.sh`, V9) + `flyhead.sim.reflex_sim synthetic`, 2 arms x 3 seeds, `experiments/loom_005/stage6_eval.py` | **STAGE 6 SIM PASSED**: 0 contacts, 0 early takeovers, reaction 2.6 s, all arrived |

Stage 3 on the synthetic arena: the open arena lets the evaluator's "loom onset" fire at 1.3 s while
the person is still about 2.1 m away, the same evaluation flaw recorded for person_right in
`experiments/loom_005/RESULTS.md`; escapes still followed (distance 0.92 -> 1.43-1.47 m within 3 s,
then ~9.7 s flights). Pipeline behaviour reproduces; the recorded-map numbers do not apply.

Fixed while verifying:

* `flyhead.fly.model.Brain` now creates the weight-cache directory (the upstream loader does not;
  a fresh clone failed on the first brain run).
* The synthetic arena now writes the height layers (`floor.npy`, `obst_hmin/hmax.npy`,
  `obst_bins.npy`). Without the floor layer the navigator had no LiDAR height and `brain_link`
  ignored every scan, so stage 6 ran with a permanently stale brain. Stage 3 output is unchanged.
* `.[dev]` now includes scipy (the tests and the blind simulation import `navmap`).

Not covered: `robot/` on real hardware (ROS 2, DIABLO and Unitree SDKs), the operator monitor UI,
and the numbers that depend on the private recorded maps.
