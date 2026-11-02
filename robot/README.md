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

### DIABLO reporting 0 V and 0% while powered

On the tested chassis, short UART push frames advertised all seven telemetry
fields. The driver decoded past the payload and published invalid battery and
motor values. The [driver patch](patches/diablo-telemetry.patch) checks the
frame length before decoding and requests all seven fields at 50 Hz. The
chassis node waits for fresh battery and status feedback before starting its
movement worker. A genuine 0% reading with valid voltage is still reported.

The patch targets the external `DDTRobot/diablo_ros2` source tree. With the
chassis driver stopped, run these commands from that tree, using the absolute
path to your FlyHead checkout:

```sh
git apply --check /path/to/FlyHead/robot/patches/diablo-telemetry.patch
git apply /path/to/FlyHead/robot/patches/diablo-telemetry.patch
```

Rebuild and install `diablo_utils` and `diablo_ctrl` in the robot's ROS 2
workspace. Check that the bridge launches the rebuilt node and that it loads
the rebuilt SDK. With motion idle, start the chassis from the console and
inspect `status.robot.battery` in the compute server's `/diagnostics`.
Verify that new samples arrive with plausible voltage and charge. The
existing low-battery stop still applies below 15%.
