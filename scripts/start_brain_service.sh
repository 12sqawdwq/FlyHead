#!/bin/bash
# Start the fly-brain service (flyhead.fly.service) in tmux on the GPU host. No robot I/O.
#   bash scripts/start_brain_service.sh RUN_NAME        -> runs/RUN_NAME/brain_windows.jsonl
#   LOOM_DECODER=9 XT_BRAIN_PORT=8095 bash scripts/start_brain_service.sh RUN_NAME
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${FLYHEAD_BRAIN_PYTHON:-$ROOT/.venv-brain/bin/python}"
RUN="$ROOT/runs/${1:?run name}"
PORT="${XT_BRAIN_PORT:-8095}"
SESSION="${XT_BRAIN_TMUX_SESSION:-flyhead-brain}"
if tmux has-session -t "$SESSION" 2>/dev/null; then echo "brain service already running ($SESSION)"; exit 1; fi
[ -e "$RUN" ] && { echo "$RUN exists; use a new run name"; exit 1; }
mkdir -p "$ROOT/logs"
printf -v COMMAND '%q ' env "PYTHONPATH=$ROOT" OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 \
    "TRITON_CACHE_DIR=${TRITON_CACHE_DIR:-$ROOT/cache/triton}" \
    "$PYTHON" -u -m flyhead.fly.service "$RUN" --port "$PORT" --decoder "${LOOM_DECODER:-4}"
tmux new-session -d -s "$SESSION" -c "$ROOT" "$COMMAND >> $ROOT/logs/brain_service.log 2>&1"
echo "brain service starting: $RUN, port $PORT, decoder ${LOOM_DECODER:-4}, log logs/brain_service.log"
