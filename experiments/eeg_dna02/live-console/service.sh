#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
name=xt-eeg-console
case "${1:-status}" in
 start)
  if tmux has-session -t "$name" 2>/dev/null; then echo 'Already running'; exit 0; fi
  if [ -f console.log ]; then mv console.log console.previous.log; fi
  tmux new-session -d -s "$name" -c "$PWD" '<SERVER_ROOT>/slam/venv/bin/python -u live-console/server.py >console.log 2>&1'
  ;;
 stop) tmux send-keys -t "$name" C-c ;;
 status) tmux has-session -t "$name" && echo 'EEG web session running; robot enable is independent' ;;
 *) echo 'Usage: service.sh start|stop|status'; exit 2 ;;
esac
