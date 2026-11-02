# loom_005 — LiDAR virtual retina, obstacle avoidance and loom escape

Date: 2026-10-10. Owner request: deploy the full-connectome fly brain on the 5090D as the
decision maker for obstacle avoidance and escape from looming, through stage 5 (physical
execution), with the operator unplugging the charger for physical tests.

## Layers (kept separate in every record)

| Layer | What it is | What it is not |
|---|---|---|
| Connectome simulation | FlyWire v783 LIF, 138639 neurons, 15091983 connection records (flywire_lif_001) | not a calibrated fly |
| Stimulus encoders | Engineering proxies from LiDAR: per-eye loom (angular expansion) -> LC4/LPLC2; free space ahead -> LC9 | not retinal reconstruction, not biological vision |
| Neural counts | Spikes per root_id per window | not motor commands |
| Shadow intent | Fixed decoder formula on descending-neuron rates | not executed motion |
| Executed command | Shadow intent after the host safety envelope (may only reduce or zero) | never planner output |

No navigation script, planner or constant speed stands in for a neural decision.
Anatomical side, LiDAR field side and robot yaw sign are three separate tables;
the field->eye assignment and the yaw sign are calibration items (stage 2/3), not assumptions.

## Stages and gates

0. Contracts: registry by exact cell_type + root_id + model_index (annotation SHA locked),
   message formats, run directories. Gate: registry matches the model index; no synonym unions.
1. Encoder + budget: LiDAR retina implemented; brain window budget measured on the live GPU.
   Gate: per-window compute within the chosen window (100 or 200 ms) at p95.
2. Offline replay of recorded sessions (raw.xt through the SLAM engine -> retina -> brain).
   Gate: loom input rises on approach to walls; LC4/LPLC2 -> DNp01/DNp02/DNp04/DNp11
   responses are side-consistent; no saturation (input at ceiling < 20 % of windows).
3. Closed-loop simulation (sim2 kinematics, ray-cast scans) brain -> decoder -> safety.
   Gate: fewer contacts than a blind straight-line baseline; escape responses to a moving
   looming object; locked before running.
4. Shadow mode on the robot: live sensors, brain intents logged, robot not driven by them.
   Gate: end-to-end source age within budget; intents plausible against logged situations.
5. Physical execution (authorized by the owner 2026-10-10): crouched, <= 0.15 m/s,
   geofenced area, RC supervisor, short sessions; then step up only by recorded amendment.

Executed runs are never re-run in place; amendments get new run directories.
