#!/bin/bash
# Start Xvfb, robot_state_publisher (twice) and RViz2, then replay one recorded scene and record the window.
#   run_scene.sh SCENE RUNS_DIR CLOUD.npy OUT.mp4 [replay.py options]
# Isolated: ROS domain 77, discovery limited to localhost. No robot is involved.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCENE=$1; RUNS=$2; CLOUD=$3; OUT=$4; shift 4

set +u; source /opt/ros/jazzy/setup.bash; set -u
export ROS_DOMAIN_ID=77 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export DISPLAY=:99 LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb XDG_RUNTIME_DIR=/tmp/xdg
mkdir -p "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"

WORK=$(mktemp -d)
ASSETS="$(cd "$HERE/../viz3d/assets/diablo" && pwd)"
sed "s#file://\$(find diablo_simulation)/meshes/#file://$ASSETS/#g" "$ASSETS/diablo_simulation.urdf" > "$WORK/robot.urdf"
python3 - "$WORK" <<'PY'
import json, sys
w = sys.argv[1]
u = open(w + '/robot.urdf', encoding='utf-8').read()
for name, prefix in (('main', ''), ('blind', 'blind/')):
    # robot_state_publisher reads a parameter file; JSON is valid YAML
    node = '/blind/robot_state_publisher' if prefix else '/robot_state_publisher'
    open('%s/%s.yaml' % (w, name), 'w', encoding='utf-8').write(json.dumps({node: {'ros__parameters': {'robot_description': u, 'frame_prefix': prefix}}}))
PY

cleanup() { kill $(jobs -p) 2>/dev/null; wait 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

Xvfb :99 -screen 0 1600x900x24 -nolisten tcp >/dev/null 2>&1 &
sleep 1
/opt/ros/jazzy/lib/robot_state_publisher/robot_state_publisher --ros-args --params-file "$WORK/main.yaml" >/dev/null 2>&1 &
/opt/ros/jazzy/lib/robot_state_publisher/robot_state_publisher --ros-args -r __ns:=/blind --params-file "$WORK/blind.yaml" >/dev/null 2>&1 &
rviz2 -d "$HERE/flyhead.rviz" >"$WORK/rviz.log" 2>&1 &
python3 "$HERE/replay.py" "$SCENE" --runs "$RUNS" --cloud "$CLOUD" --out "$OUT" --display :99 "$@"
rc=$?
grep -iE 'error|fatal' "$WORK/rviz.log" | head -8
exit $rc
