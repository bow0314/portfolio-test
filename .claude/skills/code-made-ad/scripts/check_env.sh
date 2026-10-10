#!/usr/bin/env bash
# 檢查製作影片所需軟體，只回報、不安裝。
ok(){ printf "OK      %s\n" "$1"; }
miss(){ printf "MISSING %s\n" "$1"; }
chk(){ command -v "$1" >/dev/null 2>&1 && ok "$1 ($($1 $2 2>&1 | head -1))" || miss "$1"; }
chk blender --version
chk python3 --version
chk node --version
chk ffmpeg -version
for m in numpy scipy cv2 PIL; do python3 -c "import $m" 2>/dev/null && ok "python:$m" || miss "python:$m"; done
if [ -d node_modules/puppeteer ] || npm ls -g puppeteer >/dev/null 2>&1; then ok "puppeteer"; else miss "puppeteer"; fi
