# RViz2 replay of recorded simulations

Replays recorded closed-loop simulation windows into a real RViz2 and records its window, for
`docs/media/rviz/`. Nothing is re-simulated, and no robot is connected: the scripts publish visualization
data only, on ROS domain 77 with discovery limited to localhost.

| Shown | Source | Nature |
| --- | --- | --- |
| Robot pose, decoder state, rates, paths | `flyhead.sim.loom_sim` / `reflex_sim` records | recorded; poses interpolated between 100 ms windows for display |
| Robot model | vendor `diablo_simulation.urdf` and meshes, through `robot_state_publisher` and `RobotModel` | vendor simulation meshes, not checked against this robot |
| Leg pose | URDF zero pose | display choice, not dynamics |
| Wheel spin | integrated from recorded v and w | display only |
| Person / object | simulation's 0.25 m cylinder | radius recorded; 1.7 m height is display only |
| Site cloud | saved SLAM `map.ply`, up to 80,000 points within 14 m, 0.12 to 2 m above the floor (floor returns dropped for display) | real map, downsampled |

## Environment

Ubuntu 24.04 and ROS 2 Jazzy with these packages, in an environment of its own:

```bash
apt-get install --no-install-recommends ros-jazzy-rviz2 ros-jazzy-rviz-default-plugins ros-jazzy-robot-state-publisher ros-jazzy-rclpy ros-jazzy-rmw-fastrtps-cpp ros-jazzy-tf2-ros-py xvfb x11-apps ffmpeg libgl1-mesa-dri fonts-dejavu-core python3-numpy
```

RViz2 renders with Mesa software OpenGL under Xvfb, so no display or GPU is needed.

## Run

The cloud is an N × 3 float array saved from the map package:

```bash
python -c "import numpy as np; from flyhead.slam.reloc import load_points; np.save('map_xyz.npy', np.asarray(load_points('MAP_PACKAGE/map.ply'), 'f4')[:, :3])"
bash tools/rviz_replay/record_all.sh runs/real_suite runs/viz3d_src/stage6 map_xyz.npy docs/media/rviz
```

One scene:

```bash
bash tools/rviz_replay/run_scene.sh person_front runs/real_suite map_xyz.npy out.mp4 --caption "SIM"
```

The map package and run records are not in the repository, so regeneration needs your own runs.
