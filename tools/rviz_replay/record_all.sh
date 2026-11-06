#!/bin/bash
# Record every simulation scene in RViz2. Paths are WSL paths.
#   record_all.sh SUITE_RUNS STAGE6_RUNS CLOUD.npy OUT_DIR
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SUITE=$1; STAGE6=$2; CLOUD=$3; OUT=$4
mkdir -p "$OUT"
one() {  # scene runs speed caption
  bash "$HERE/run_scene.sh" "$1" "$2" "$CLOUD" "$OUT/$1.mp4" --speed "$3" --warmup 12 --caption "$4" 2>&1 | grep -E 'done|rror|Traceback'
  sleep 2
}
for s in person_front person_left person_right loom_front loom_left loom_right; do
  one "$s" "$SUITE" 1 "RViz2 replay - SIM on real map - $s - solid fly brain, ghost no brain"
done
one wall_ahead "$SUITE" 2 "RViz2 replay - SIM on real map - wall_ahead 2x - solid fly brain, ghost no brain"
one roam_open "$SUITE" 3 "RViz2 replay - SIM on real map - roam_open 3x - solid fly brain, ghost no brain"
one stage6 "$STAGE6" 4 "RViz2 replay - SIM on real map - stage 6 4x - solid reflex arm, ghost planner arm"
echo ALL_DONE
