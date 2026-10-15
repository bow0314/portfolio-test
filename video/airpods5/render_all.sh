#!/usr/bin/env bash
# 4 個 Blender 背景並行渲染全部 11 鏡（每個負責 f % 4 == i 的格），已存在的格會跳過。
# 用法：./render_all.sh FRAMES_DIR [SCALE] [SAMPLES]
set -e
cd "$(dirname "$0")"
OUT=${1:-frames}; SCALE=${2:-0.6667}; SAMPLES=${3:-12}; N=${N:-4}
mkdir -p "$OUT"
for i in $(seq 0 $((N-1))); do
  blender -b -P scene.py -- --shots 1,2,3,4,5,6,7,8,9,10,11 --out "$OUT" --scale "$SCALE" --samples "$SAMPLES" --shard "$i/$N" > "$OUT/log_$i.txt" 2>&1 &
done
wait
echo "render done"
