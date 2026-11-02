# Stage 3 locked run stage3_002 (PROTOCOL_STAGE3.md). Verifies the lock, then runs every scenario once.
set -e
cd "$(dirname "$0")"
PY=<SERVER_ROOT>/inference_service/deployments/flywire_lif_001/env/bin/python
sha256sum -c ${STAGE3_LOCK:-protocol_lock_stage3.sha256}
OUT=runs/${STAGE3_RUN:-stage3_002}; mkdir $OUT
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 TRITON_CACHE_DIR=$PWD/triton_cache
for spec in "wall_ahead 40" "roam_open 120" "person_front 25" "person_left 25" "person_right 25"; do
  set -- $spec
  for arm in brain blind; do
    $PY sim_brain.py $1 $arm $2 $OUT/${1}_${arm}.jsonl 2>>$OUT/stderr.txt
    echo "done $1 $arm"
  done
done
$PY sim_report.py $OUT/*.jsonl > $OUT/REPORT.txt
$PY ${STAGE3_EVAL:-stage3_eval.py} $OUT > $OUT/EVAL.txt
echo ALL DONE
