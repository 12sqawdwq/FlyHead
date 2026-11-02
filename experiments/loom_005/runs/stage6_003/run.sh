set -e
cd <SERVER_ROOT>/inference_service/mappings/loom_005
sha256sum -c protocol_lock_stage6_003.sha256 > /dev/null
(env LOOM_DECODER=9 OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 TRITON_CACHE_DIR=$PWD/triton_cache <SERVER_ROOT>/inference_service/deployments/flywire_lif_001/env/bin/python -u brain_service.py runs/stage6_003/brain_svc 8096 > runs/stage6_003/svc.log 2>&1 &)
sleep 25
for seed in 1 2 3; do for arm in reflex planner; do
  XT_BRAIN_DIR=<SERVER_ROOT>/inference_service/mappings/loom_005 XT_BRAIN_PORT=8096 timeout 260 <SERVER_ROOT>/slam/deployments/distributed_control/venv/bin/python sim_reflex.py <SERVER_ROOT>/inference_service/mappings/loom_005/stage6_server <SERVER_ROOT>/slam/deployments/distributed_control/maps/onboard_20260926_manual_cleanup_20261005 $arm $seed runs/stage6_003/${arm}_seed$seed.jsonl >> runs/stage6_003/sim.log 2>&1 || echo "$arm $seed exit $?" >> runs/stage6_003/sim.log
done; done
pkill -f 'brain_service.py runs/stage6_00[3]' || true
<SERVER_ROOT>/slam/deployments/distributed_control/venv/bin/python stage6_eval.py runs/stage6_003 > runs/stage6_003/EVAL.txt
echo ALL DONE
