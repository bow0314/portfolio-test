# AirPods 5〈世界同樂〉60 秒廣告

全部用程式產生：Blender（Python）建模、運鏡與渲染，numpy 合成配樂與音效（科技感電子流行，F–G–Em–Am），PIL 做字卡和對話泡泡，ffmpeg 輸出。
沒有用 AI 生圖、生影片，也沒有用任何音檔或圖檔素材。

| 檔案 | 用途 |
|---|---|
| `timeline.json` | 共用時間軸：11 鏡起訖、轉場、字卡、對話泡泡（120 BPM，一小節 2 秒，剪點落在小節線） |
| `scene.py` | Blender 場景：耳機、充電盒、低多邊形地球、市集／海灘／街頭樂團、各鏡運鏡 |
| `render_all.sh` | 4 個 Blender 背景並行渲染全部鏡頭 |
| `music.py` | 配樂與音效合成，另可輸出波形＋頻譜檢查圖 |
| `compose.py` | 合成：轉場、光暈、暗角、顆粒、字卡、泡泡 → MP4（H.264 + AAC） |

## 重做一次

```bash
apt-get install -y blender fonts-noto-cjk libegl1 libegl-mesa0 libgl1-mesa-dri
pip install numpy scipy pillow

./render_all.sh /path/to/frames 0.6667 12            # 1280×720、12 samples
blender -b -P scene.py -- --shots 7 --out /path/to/frames --scale 0.6667 --anchors-only   # 第 7 鏡閃光位置
python3 music.py music.wav music_check.png
python3 compose.py /path/to/frames music.wav airpods5.mp4   # 輸出 1920×1080
```

字卡規格依據：[Apple Newsroom](https://www.apple.com/newsroom/2026/09/apple-introduces-airpods-5-with-best-in-class-open-ear-active-noise-cancellation/)、[AirPods 5 技術規格](https://support.apple.com/en-us/148759)。
