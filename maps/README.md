# Map packages

Map packages are site data and are not versioned. A package is a directory with
`map.yaml` + `map.pgm` (0 occupied / 254 free / 205 unknown, 0.05 m cells), optional
height layers (`floor.npy`, `obst_hmin.npy`, `obst_hmax.npy`, `obst_bins.npy`) and, for
relocalization, the base point cloud `map.ply`.

* Build one from a recorded session: `python tools/export_session_map.py` (see `docs/slam_operations.md`).
* For simulation without a recording: `python -m flyhead.sim.synthetic_map maps/synthetic_arena`.
