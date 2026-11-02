# Stage 3 runs (retina v3). Each run gets its own output file; nothing is re-run in place.
set -e
cd "$(dirname "$0")"
PY=<SERVER_ROOT>/inference_service/deployments/flywire_lif_001/env/bin/python
OUT=runs/stage3_001; mkdir -p $OUT
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 TRITON_CACHE_DIR=$PWD/triton_cache
for spec in "wall_ahead 40" "roam_open 120" "loom_front 25" "loom_left 25" "loom_right 25"; do
  set -- $spec
  for arm in brain blind; do
    [ -f $OUT/${1}_${arm}.jsonl ] && continue
    $PY sim_brain.py $1 $arm $2 $OUT/${1}_${arm}.jsonl 2>>$OUT/stderr.txt
    echo "done $1 $arm"
  done
done
$PY sim_report.py $OUT/*.jsonl > $OUT/REPORT.txt
echo ALL DONE
