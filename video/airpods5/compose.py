"""AirPods 5〈世界同樂〉合成：渲染格 + 字卡 + 對話泡泡 + 轉場 + 光暈/暗角/顆粒 → ffmpeg 輸出 MP4。

用法：python3 compose.py FRAMES_DIR MUSIC.wav OUT.mp4 [--from S] [--to S] [--scale 1.0] [--lang zh|en]
缺格時用同一鏡最近的已渲染格代替（方便渲染途中先看預覽）。
"""
import glob, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "timeline.json"), encoding="utf-8"))
FPS, W0, H0, DUR = TL["fps"], TL["width"], TL["height"], TL["duration"]

FR, MUSIC, OUT = sys.argv[1:4]
def opt(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
T_FROM, T_TO, SC = opt("--from", 0), opt("--to", DUR), opt("--scale", 1.0)
LANG = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "zh"  # zh：中文字幕、en：英文字幕
W, H = int(W0 * SC) // 2 * 2, int(H0 * SC) // 2 * 2
def px(v): return int(round(v * SC))

BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_IDX = {"jp": 0, "tc": 3}
_fonts = {}
def font(size, lang="tc", bold=True):
    k = (size, lang, bold)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(BOLD if bold else REG, px(size), index=FONT_IDX[lang])
    return _fonts[k]

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(t): t = clamp(t); return 1 - (1 - t) ** 3
def back_out(t, s=1.7):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1

# ---------------------------------------------------------------- 讀格
SHOTS = TL["shots"]
_frame_lists = {}
def shot_frames(sid):
    if sid not in _frame_lists:
        fs = sorted(glob.glob(os.path.join(FR, f"shot{sid:02d}", "*.png")))
        _frame_lists[sid] = {int(os.path.basename(f)[:4]): f for f in fs}
    return _frame_lists[sid]

def load(sid, f):
    fl = shot_frames(sid)
    if not fl:
        return Image.new("RGB", (W, H), (40, 40, 48))
    if f not in fl:
        f = min(fl, key=lambda k: abs(k - f))
    im = Image.open(fl[f]).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    return im

_anchors = {}
def anchor(sid, f):
    if sid not in _anchors:
        a = {}
        for p in glob.glob(os.path.join(FR, f"shot{sid:02d}", "anchors_*.json")):
            a.update({int(k): v for k, v in json.load(open(p)).items()})
        _anchors[sid] = a
    a = _anchors[sid]
    if not a: return (0.5, 0.4)
    if f not in a: f = min(a, key=lambda k: abs(k - f))
    return a[f]

def shot_at(t):
    for s in SHOTS:
        if s["start"] <= t < s["end"]: return s
    return SHOTS[-1]

# ---------------------------------------------------------------- 後製效果
yy, xx = np.mgrid[0:H, 0:W]
_r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
VIGNETTE = (1 - 0.22 * np.clip(_r - 0.45, 0, None) ** 1.6)[..., None].astype(np.float32)
rng = np.random.default_rng(1)

def grade(im):
    a = np.asarray(im).astype(np.float32) / 255
    lum = a.mean(2, keepdims=True)
    hi = np.clip((lum - 0.78) / 0.22, 0, 1) * a
    glow = Image.fromarray((hi * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(px(22)))
    a = a + np.asarray(glow).astype(np.float32) / 255 * 0.35
    a = a * VIGNETTE
    a = a + rng.normal(0, 0.007, (H, W, 1)).astype(np.float32)
    return np.clip(a, 0, 1)

# ---------------------------------------------------------------- 字卡
def text_layer(lines, size, lang="tc"):
    """白字＋柔和陰影，回傳 RGBA 圖。第一行大、其餘小一點。"""
    fonts = [font(size if i == 0 else int(size * 0.72), lang) for i in range(len(lines))]
    boxes = [f.getbbox(l) for f, l in zip(fonts, lines)]
    widths = [b[2] - b[0] for b in boxes]
    gap = px(14)
    heights = [f.size * 1.18 for f in fonts]
    tw, th = max(widths), int(sum(heights) + gap * (len(lines) - 1))
    pad = px(40)
    lay = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", lay.size, (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(lay), ImageDraw.Draw(sh)
    y = pad
    for f, l, h_, b in zip(fonts, lines, heights, boxes):
        d.text((pad - b[0], y), l, font=f, fill=(255, 255, 255, 255))
        ds.text((pad - b[0], y + px(3)), l, font=f, fill=(20, 20, 40, 230), stroke_width=px(4), stroke_fill=(20, 20, 40, 230))
        y += h_ + gap
    sh = sh.filter(ImageFilter.GaussianBlur(px(10)))
    return Image.alpha_composite(sh, lay), pad

_card_cache = {}
def draw_card(canvas, c, t):
    if not (c["start"] <= t < c["end"]): return
    key = id(c)
    if key not in _card_cache:
        lines = c.get("lines_en", c["lines"]) if LANG == "en" else c["lines"]
        _card_cache[key] = text_layer(lines, c["size"])
    lay, pad = _card_cache[key]
    k_in = clamp((t - c["start"]) / 0.55)
    k_out = 1 - clamp((t - (c["end"] - 0.35)) / 0.35) if c["end"] < DUR else 1.0
    alpha = ease_out(k_in) * k_out
    if alpha <= 0: return
    blur = (1 - ease_out(k_in)) * 12
    rise = (1 - ease_out(k_in)) * px(36)
    im = lay.filter(ImageFilter.GaussianBlur(px(blur))) if blur > 0.3 else lay
    if alpha < 1:
        a = im.getchannel("A").point(lambda v: int(v * alpha)); im = im.copy(); im.putalpha(a)
    w, h = im.size
    if c["pos"] == "lower_left": x, y = px(110) - pad, H - px(110) - h + pad
    elif c["pos"] == "upper_center": x, y = (W - w) // 2, px(110) - pad
    else: x, y = (W - w) // 2, (H - h) // 2 - px(40)
    canvas.alpha_composite(im, (int(x), int(y + rise)))

# ---------------------------------------------------------------- 對話泡泡
def bubble_img(text, lang, tag, color_tag):
    f = font(54, lang)
    b = f.getbbox(text)
    tw, th = b[2] - b[0], f.size * 1.2
    padx, pady = px(40), px(26)
    bw, bh = int(tw + padx * 2), int(th + pady * 2)
    tail = px(34)
    ft = font(26, "tc")
    tb = ft.getbbox(tag)
    tagw, tagh = tb[2] - tb[0] + px(28), px(44)
    img = Image.new("RGBA", (bw + px(40), bh + tail + tagh // 2 + px(40)), (0, 0, 0, 0))
    ox, oy = px(20), px(20) + tagh // 2
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); dsh = ImageDraw.Draw(sh)
    dsh.rounded_rectangle((ox, oy + px(6), ox + bw, oy + bh + px(6)), px(40), fill=(30, 20, 60, 90))
    sh = sh.filter(ImageFilter.GaussianBlur(px(10)))
    img.alpha_composite(sh)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((ox, oy, ox + bw, oy + bh), px(40), fill=(255, 255, 255, 255))
    cx = ox + bw // 2
    d.polygon([(cx - px(22), oy + bh - 2), (cx + px(22), oy + bh - 2), (cx, oy + bh + tail)], fill=(255, 255, 255, 255))
    d.text((ox + padx - b[0], oy + pady - b[1] + (th - (b[3] - b[1])) / 2 - px(4)), text, font=f, fill=(40, 40, 60, 255))
    # 語言小標籤
    d.rounded_rectangle((ox + px(26), oy - tagh // 2, ox + px(26) + tagw, oy + tagh // 2), tagh // 2, fill=color_tag)
    d.text((ox + px(26) + px(14) - tb[0], oy - tagh // 2 + (tagh - (tb[3] - tb[1])) / 2 - tb[1]), tag, font=ft, fill=(255, 255, 255, 255))
    return img, (cx, oy + bh + tail)

_bub_cache = {}
def draw_bubble(canvas, bb, t, f_local):
    if not (bb["start"] <= t < bb["end"]): return
    flipped = t >= bb["flip"]
    key = (id(bb), flipped)
    if key not in _bub_cache:
        if flipped and LANG == "en": _bub_cache[key] = bubble_img(bb["dst_en"], "tc", "English", (77, 150, 255, 255))
        elif flipped: _bub_cache[key] = bubble_img(bb["dst"], "tc", "中文", (77, 150, 255, 255))
        else: _bub_cache[key] = bubble_img(bb["src"], "jp", bb["src_lang"], (255, 111, 97, 255))
    img, (tx, ty) = _bub_cache[key]
    s = back_out((t - bb["start"]) / 0.3)
    sx = s
    df = t - bb["flip"]
    if -0.12 < df < 0: sx *= clamp(-df / 0.12)            # 翻面：先壓扁
    elif 0 <= df < 0.18: sx *= back_out(df / 0.18, 2.2)    # 再彈開成中文
    if t > bb["end"] - 0.2: s *= clamp((bb["end"] - t) / 0.2); sx = min(sx, s)
    if s <= 0.01 or sx <= 0.01: return
    w, h = img.size
    im = img.resize((max(1, int(w * sx)), max(1, int(h * s))), Image.BILINEAR)
    ax, ay = anchor(bb["shot"], f_local)
    x = ax * W - tx * sx
    y = ay * H - px(20) - ty * s
    x = clamp(x, px(30), W - im.size[0] - px(30)); y = clamp(y, px(30), H - im.size[1] - px(30))
    canvas.alpha_composite(im, (int(x), int(y)))

def draw_glint(canvas, sid, f_local, t, t0):
    k = (t - t0) / 0.6
    if not (0 <= k <= 1): return
    a = math.sin(math.pi * k)
    ax, ay = anchor(sid, f_local)
    cx, cy = ax * W, ay * H
    L = px(260) * (0.6 + 0.4 * a)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    rot = k * 0.6
    for ang in (0, math.pi / 2, math.pi / 4, 3 * math.pi / 4):
        ln = L if ang in (0, math.pi / 2) else L * 0.45
        dx, dy = math.cos(ang + rot) * ln, math.sin(ang + rot) * ln
        d.polygon([(cx - dx, cy - dy), (cx - dy * 0.03, cy + dx * 0.03), (cx + dx, cy + dy), (cx + dy * 0.03, cy - dx * 0.03)], fill=(255, 255, 255, int(230 * a)))
    d.ellipse((cx - px(40), cy - px(40), cx + px(40), cy + px(40)), fill=(255, 255, 255, int(200 * a)))
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(px(3))))
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(px(18))))

# ---------------------------------------------------------------- 主迴圈
def base_frame(t):
    s = shot_at(t)
    f = min(int(round((t - s["start"]) * FPS)), int((s["end"] - s["start"]) * FPS) - 1)
    return s, f, load(s["id"], f)

def render(g):
    t = g / FPS
    s, f, im = base_frame(t)
    dt = t - s["start"]
    a = np.asarray(im).astype(np.float32) / 255
    idx = SHOTS.index(s)
    if s["in"] == "dissolve" and dt < 0.3 and idx > 0:
        p = SHOTS[idx - 1]
        prev = np.asarray(load(p["id"], int((p["end"] - p["start"]) * FPS) - 1)).astype(np.float32) / 255
        k = ease_out(dt / 0.3); a = prev * (1 - k) + a * k
    a = grade(Image.fromarray((a * 255).astype(np.uint8)))
    if s["in"] == "flash" and dt < 0.45:
        k = math.exp(-dt / 0.12); a = a + (1 - a) * k
    nxt = SHOTS[idx + 1] if idx + 1 < len(SHOTS) else None
    if nxt and nxt["in"] == "flash" and s["end"] - t < 0.12:
        k = 1 - (s["end"] - t) / 0.12; a = a + (1 - a) * k * 0.6
    if s["in"] == "fade_black" and dt < 0.7:
        a = a * ease_out(dt / 0.7)
    canvas = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
    if "glint" in s: draw_glint(canvas, s["id"], f, t, s["glint"])
    for bb in TL["bubbles"]:
        if bb["shot"] == s["id"]: draw_bubble(canvas, bb, t, f)
    for c in TL["cards"]: draw_card(canvas, c, t)
    out = canvas.convert("RGB")
    if t > DUR - 0.5:  # 片尾收黑
        out = Image.blend(Image.new("RGB", out.size), out, clamp((DUR - t) / 0.5) ** 0.7)
    return out

def main():
    g0, g1 = int(T_FROM * FPS), int(T_TO * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-ss", str(T_FROM), "-t", str(T_TO - T_FROM), "-i", MUSIC,
           "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for g in range(g0, g1):
        p.stdin.write(render(g).tobytes())
        if g % 48 == 0: print(f"compose {g / FPS:5.1f}s", flush=True)
    p.stdin.close(); p.wait()
    print("wrote", OUT)

if __name__ == "__main__":
    main()
