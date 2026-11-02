# Robot deployment

Runs on the robot (DIABLO wheel-legged, Raspberry Pi 4B, ROS 2 Foxy). Standalone: it does not
import the `flyhead` package and is started only by the control server over SSH.

| File | Role |
| --- | --- |
| `run.sh` | entry point: sources ROS, takes an exclusive lock, starts `bridge.py` in its own session |
| `bridge.py` | ROS I/O: LiDAR + IMU + battery + chassis status out (binary frames on stdout), leased velocity commands and posture requests in (JSON on stdin); link-loss return along the driven path |
| `transport.py` | bounded output queue (drops camera frames before sensor frames) |
| `camera/camera.yaml` | optional Orbbec camera parameters (off by default: CPU and USB budget) |

Requirements on the robot: `/opt/ros/foxy`, the DIABLO workspace (`diablo_ctrl`, `motion_msgs`),
the Unitree L1 LiDAR ROS 2 node and, optionally, `orbbec_camera`. Locations default to
`~/ros2_ws`, `~/diablo_ws`, `~/unilidar_sdk`; override with `XT_ROS_WS`, `XT_DIABLO_WS`,
`XT_LIDAR_EXE`, `XT_CHASSIS_EXE`, `XT_CAMERA_EXE`.

Motion needs `XT_CHASSIS_DISABLED=0` and `XT_REMOTE_MOTION_ENABLED=1`, both passed by the server
only when it was itself started with them. Every velocity carries a deadline ≤ 0.3 s on the robot
clock; without server traffic for 2 s the bridge zeroes motion.
