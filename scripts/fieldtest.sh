#!/bin/bash
# Field-test launcher on the compute host: brain service + control server with one command.
#   bash scripts/fieldtest.sh up            # charging lock ON: sensors, SLAM, brain shadow; no motion
#   bash scripts/fieldtest.sh up motion     # both motion opt-ins set; speed ceiling XT_MAX_V (default 0.10 m/s)
#   bash scripts/fieldtest.sh status        # sessions, ports, robot link, battery, brain
#   bash scripts/fieldtest.sh down          # stop the server (ends any robot session), then the brain service
# Site settings are read from configs/local.env (git-ignored), for example:
#   XT_ROBOT_HOST=robot  XT_ROBOT_ROOT=/home/<user>/FlyHead  XT_MAP=maps/<package>
#   XT_PYTHON=.venv/bin/python  FLYHEAD_BRAIN_PYTHON=.venv-brain/bin/python  XT_BRAIN_PORT=8095
# Motion still needs the chassis to be started from the console, and an operator with the RC at the robot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f configs/local.env ] && { set -a; . configs/local.env; set +a; }
PORT="${XT_API_PORT:-8091}"
BRAIN_PORT="${XT_BRAIN_PORT:-8095}"
export XT_BRAIN_PORT="$BRAIN_PORT"

status() {
    echo "sessions: $(tmux ls 2>/dev/null | grep -oE '^flyhead-(server|brain)' | tr '\n' ' ')"
    for p in "$PORT" "$BRAIN_PORT"; do
        ss -ltn | grep -q ":$p " && echo "port $p: listening" || echo "port $p: closed"
    done
    curl -s -m 5 "127.0.0.1:$PORT/diagnostics" | "${XT_PYTHON:-python3}" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit("control server: no answer")
s = d["status"]; r = s.get("robot") or {}; b = s.get("brain") or {}; sl = s.get("slam") or {}
bat = r.get("battery") or {}
print("charging lock:", s.get("chassis_disabled"), "| speed ceiling:", s.get("speed_limit_max"))
print("robot session:", d["session_running"], "| run:", s.get("run"), "| lidar:", r.get("lidar_running"), "| chassis:", r.get("chassis_running"))
print("rates:", s.get("rates"))
print("battery:", bat.get("voltage"), "V", bat.get("pct"), "% (age %s s)" % bat.get("age"))
print("localization:", (sl.get("reloc") or {}).get("state"), "fitness", sl.get("fitness"))
print("brain: enabled", b.get("enabled"), "mode", b.get("mode"), "connected", b.get("connected"))
print("background errors:", d.get("errors") or "none")'
}

case "${1:-}" in
up)
    MODE="${2:-locked}"
    if tmux has-session -t flyhead-server 2>/dev/null; then echo "flyhead-server already running; run 'down' first"; exit 1; fi
    if ! tmux has-session -t flyhead-brain 2>/dev/null; then
        LOOM_DECODER="${LOOM_DECODER:-9}" bash scripts/start_brain_service.sh "field_$(date +%Y%m%dT%H%M%S)"
        for _ in $(seq 90); do ss -ltn | grep -q ":$BRAIN_PORT " && break; sleep 2; done
        ss -ltn | grep -q ":$BRAIN_PORT " || { echo "brain service did not come up; see logs/brain_service.log"; exit 1; }
    fi
    if [ "$MODE" = motion ]; then
        export XT_CHASSIS_DISABLED=0 XT_REMOTE_MOTION_ENABLED=1 XT_MAX_V="${XT_MAX_V:-0.10}"
    else
        export XT_CHASSIS_DISABLED=1 XT_REMOTE_MOTION_ENABLED=0 XT_MAX_V="${XT_MAX_V:-0.10}"
    fi
    XT_BRAIN_ENABLED=1 bash scripts/start_server.sh
    for _ in $(seq 30); do curl -s -m 2 "127.0.0.1:$PORT/diagnostics" >/dev/null && break; sleep 1; done
    status
    ;;
down)
    tmux kill-session -t flyhead-server 2>/dev/null && echo "control server stopped" || echo "control server was not running"
    sleep 2
    tmux kill-session -t flyhead-brain 2>/dev/null && echo "brain service stopped" || echo "brain service was not running"
    ;;
status)
    status
    ;;
*)
    sed -n '2,12p' "$0"; exit 2
    ;;
esac
