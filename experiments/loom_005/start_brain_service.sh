#!/bin/bash
# Start the loom_005 brain service in tmux (session xt-fly-brain) on the 5090D. No robot I/O.
#   bash start_brain_service.sh RUN_NAME      -> runs/RUN_NAME/brain_windows.jsonl
set -euo pipefail
cd "$(dirname "$0")"
RUN=runs/${1:?run name}
SESSION=xt-fly-brain
PY=<SERVER_ROOT>/inference_service/deployments/flywire_lif_001/env/bin/python
if tmux has-session -t "$SESSION" 2>/dev/null; then echo "brain service already running ($SESSION)"; exit 1; fi
[ -e "$RUN" ] && { echo "$RUN exists; use a new run name"; exit 1; }
tmux new-session -d -s "$SESSION" -c "$PWD" "env LOOM_DECODER=${LOOM_DECODER:-4} OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 TRITON_CACHE_DIR=$PWD/triton_cache $PY -u brain_service.py $RUN 8095 >> brain_service.log 2>&1"
echo "brain service starting: $RUN, port 8095, log brain_service.log"
