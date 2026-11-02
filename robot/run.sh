#!/bin/bash
# Started locally or directly by the compute server over SSH.
# A single bridge owns robot IO; stdout carries binary frames only.
# setsid keeps the bridge in its own session: losing the SSH link must not kill
# the link-loss return along the driven path.  The bridge exits by itself.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec 9>"$ROOT/.bridge.lock"
flock -n 9 || { echo 'Robot bridge already owned by another session' >&2; exit 73; }
source /opt/ros/foxy/setup.bash >/dev/null 2>&1
source "${XT_ROS_WS:-$HOME/ros2_ws}/install/setup.bash" >/dev/null 2>&1
source "${XT_DIABLO_WS:-$HOME/diablo_ws}/install/setup.bash" >/dev/null 2>&1
export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=1 PYTHONUNBUFFERED=1
export XT_CAM_FPS=${XT_CAM_FPS:-3}
export XT_CAM_MAX_WIDTH=${XT_CAM_MAX_WIDTH:-480}
export XT_CAMERA=${XT_CAMERA:-0}
mkdir -p "$ROOT/logs"
exec setsid -w python3 -B "$ROOT/robot/bridge.py" 2>>"$ROOT/logs/bridge.stderr.log"
