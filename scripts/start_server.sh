#!/bin/bash
# Start the control server (flyhead.server.app) in tmux on the compute host. API only:
# acquisition, chassis and posture are started later from the monitor console.
#   bash scripts/start_server.sh                                                     # charging lock on
#   XT_CHASSIS_DISABLED=0 XT_REMOTE_MOTION_ENABLED=1 bash scripts/start_server.sh   # motion allowed
#   XT_BRAIN_ENABLED=1 ...   enables fly-brain mode (needs scripts/start_brain_service.sh; off until selected)
#   XT_MAX_V=0.6 ...         raises the speed ceiling (default 0.30 m/s, never above 1.0)
# Required: XT_ROBOT_HOST (SSH alias of the robot), XT_ROBOT_ROOT (absolute FlyHead path on the robot),
#           XT_MAP (map package directory with map.ply, map.pgm, map.yaml).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${XT_PYTHON:-$ROOT/.venv/bin/python}"
ROBOT_HOST="${XT_ROBOT_HOST:?set XT_ROBOT_HOST to the robot SSH alias}"
ROBOT_ROOT="${XT_ROBOT_ROOT:?set XT_ROBOT_ROOT to the absolute FlyHead path on the robot}"
MAP="${XT_MAP:?set XT_MAP to a map package directory}"
PORT="${XT_API_PORT:-8091}"
SESSION="${XT_TMUX_SESSION:-flyhead-server}"
mkdir -p "$ROOT/logs" "$ROOT/runs"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Control server already exists: $SESSION"
    exit 1
fi
printf -v COMMAND '%q ' env "PYTHONPATH=$ROOT" "XT_CHASSIS_DISABLED=${XT_CHASSIS_DISABLED:-1}" \
    "XT_REMOTE_MOTION_ENABLED=${XT_REMOTE_MOTION_ENABLED:-0}" \
    "XT_MAX_V=${XT_MAX_V:-0.30}" "XT_BRAIN_ENABLED=${XT_BRAIN_ENABLED:-0}" "XT_BRAIN_PORT=${XT_BRAIN_PORT:-8095}" \
    "$PYTHON" -u -m flyhead.server.app --robot-host "$ROBOT_HOST" --robot-root "$ROBOT_ROOT" \
    --port "$PORT" --base "$MAP/map.ply" --nav "$MAP"
printf -v LOG '%q' "$ROOT/logs/control_server.log"
tmux new-session -d -s "$SESSION" -c "$ROOT" "$COMMAND >>$LOG 2>&1"
echo "Control API launch requested on 127.0.0.1:$PORT."
echo "Charging lock: ${XT_CHASSIS_DISABLED:-1}; remote motion opt-in: ${XT_REMOTE_MOTION_ENABLED:-0}; speed ceiling: ${XT_MAX_V:-0.30} m/s."
echo "Log: $ROOT/logs/control_server.log"
echo "No acquisition or actuator operation is started by this launcher."
