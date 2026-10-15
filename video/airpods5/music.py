"""AirPods 5〈世界同樂〉配樂與音效：全部用 numpy 從波形合成，不用任何音檔。

用法：python3 music.py OUT.wav [WAVEFORM.png]
120 BPM、C 大調，一小節 2 秒；剪點都落在 timeline.json 的鏡頭起點（小節線）。
"""
import json, os, sys
import numpy as np
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "timeline.json"), encoding="utf-8"))
SR = 44100
DUR = TL["duration"]
BEAT = 60.0 / TL["bpm"]
BAR = 4 * BEAT
N = int(SR * DUR) + SR  # 多留 1 秒給殘響，最後再裁
rng = np.random.default_rng(2026)

def mtof(m): return 440.0 * 2 ** ((m - 69) / 12)
def tvec(d): return np.arange(int(d * SR)) / SR
def env_ad(d, a=0.005, decay=None):
    t = tvec(d)
    e = np.minimum(1, t / max(a, 1e-4))
    if decay: e *= np.exp(-t / decay)
    rel = min(int(0.02 * SR), len(t))
    if rel: e[-rel:] *= np.linspace(1, 0, rel)
    return e

class Bus:
    def __init__(self, stereo=True):
        self.x = np.zeros((N, 2))
    def add(self, t0, s, gain=1.0, pan=0.0):
        i = int(round(t0 * SR))
        if i >= N: return
        s = s[: N - i]
        l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        if s.ndim == 1:
            self.x[i:i + len(s), 0] += s * gain * l * 1.414
            self.x[i:i + len(s), 1] += s * gain * r * 1.414
        else:
            self.x[i:i + len(s)] += s * gain

def bandpass(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)
def lowpass(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x, axis=0)
def highpass(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x, axis=0)
def noise(d): return rng.standard_normal(int(d * SR))

# ---------------------------------------------------------------- 樂器
def kick(level=1.0):
    t = tvec(0.45)
    f = 45 + 95 * np.exp(-t / 0.045)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.22)
    click = highpass(noise(0.45), 2000) * np.exp(-t / 0.004) * 0.25
    return (s + click) * level

def clap():
    d = 0.35; t = tvec(d)
    n = bandpass(noise(d), 900, 2600)
    e = np.zeros_like(t)
    for off in (0.0, 0.011, 0.022):
        e += (t >= off) * np.exp(-np.maximum(t - off, 0) / (0.012 if off < 0.02 else 0.13))
    return n * e * 0.55

def hat(open_=False):
    d = 0.25 if open_ else 0.08
    t = tvec(d)
    return highpass(noise(d), 7000) * np.exp(-t / (0.09 if open_ else 0.022)) * 0.22

def snare():
    d = 0.3; t = tvec(d)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    n = bandpass(noise(d), 1500, 8000) * np.exp(-t / 0.08)
    return (0.5 * body + n) * 0.5

def bass(m, d):
    t = tvec(d)
    f = mtof(m)
    ph = 2 * np.pi * f * t
    s = np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)
    return s * env_ad(d, 0.004, 0.45) * 0.55

def pad(notes, d):
    t = tvec(d)
    L = np.zeros_like(t); R = np.zeros_like(t)
    for m in notes:
        f = mtof(m)
        for det, side in ((-0.12, 0), (0.0, 2), (0.12, 1)):
            ff = f * 2 ** (det / 12)
            saw = 2 * ((ff * t + rng.random()) % 1) - 1
            if side in (0, 2): L += saw
            if side in (1, 2): R += saw
    e = np.minimum(1, t / 0.4) * np.minimum(1, (d - t) / 0.4)
    st = np.stack([L, R], 1) * e[:, None]
    return lowpass(st, 1400) * 0.05

def bell(m, d=1.6):
    t = tvec(d); f = mtof(m)
    s = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / (dd)) for r, a, dd in ((1, 1, 0.8), (2.76, 0.4, 0.3), (5.4, 0.2, 0.12), (8.9, 0.08, 0.06)))
    return s * 0.35 * np.minimum(1, t / 0.002)

def ding():
    return bell(84) + 0.7 * bell(91)

def pop_blip():
    t = tvec(0.12)
    f = 500 + 1600 * (t / 0.12)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.035) * 0.45

def case_click(close=False):
    t = tvec(0.25)
    n = bandpass(noise(0.25), 2500, 9000) * np.exp(-t / 0.006)
    thump = np.sin(2 * np.pi * (160 if close else 220) * t) * np.exp(-t / 0.03)
    s = n * 0.6 + thump * 0.5
    if not close:  # 磁鐵「啵」的第二下
        s2 = np.zeros_like(s); i = int(0.045 * SR)
        s2[i:] = (n[:-i] * 0.35 + thump[:-i] * 0.3)
        s += s2
    return s

def whoosh(d=0.9, up=True):
    t = tvec(d)
    n = noise(d)
    out = np.zeros_like(n)
    steps = 24
    for k in range(steps):  # 分段帶通掃頻
        a, b = int(k * len(n) / steps), int((k + 1) * len(n) / steps)
        u = k / steps if up else 1 - k / steps
        fc = 300 * (25 ** u)
        out[a:b] = bandpass(n, fc * 0.7, min(fc * 1.4, SR / 2 - 100))[a:b]
    e = np.sin(np.pi * t / d) ** 2
    return out * e * 0.6

def riser(d=2.0):
    t = tvec(d)
    f = 200 * 2 ** (3 * t / d)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.15
    n = highpass(noise(d), 3000) * 0.25
    return (tone + n) * (t / d) ** 2

def crash(d=2.5):
    t = tvec(d)
    return highpass(noise(d), 5000) * np.exp(-t / 0.7) * 0.4

def splash(d=1.6):
    t = tvec(d)
    body = lowpass(noise(d), 1800) * np.exp(-t / 0.35) * 0.9
    hiss = highpass(noise(d), 4000) * np.exp(-t / 0.5) * 0.25
    s = body + hiss
    for k in range(18):  # 小水滴
        t0 = rng.uniform(0.15, 1.3); i = int(t0 * SR)
        f0 = rng.uniform(900, 2400)
        tt = tvec(0.05)
        drop = np.sin(2 * np.pi * np.cumsum(f0 * (1 + 2 * tt / 0.05)) / SR) * np.exp(-tt / 0.012) * 0.25
        s[i:i + len(drop)] += drop[: len(s) - i]
    return s

def waves(d):
    t = tvec(d)
    b = np.cumsum(noise(d)); b = highpass(b / np.max(np.abs(b)), 60)
    b = lowpass(b, 900)
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * t / 3.0 - np.pi / 2)
    return b * lfo * np.minimum(1, np.minimum(t, d - t) / 0.8) * 1.4

def crowd(d):
    t = tvec(d)
    n = bandpass(noise(d), 300, 3000)
    mod = lowpass(np.abs(noise(d)), 6)
    mod = mod / mod.max()
    return n * (0.4 + mod) * np.minimum(1, np.minimum(t, d - t) / 0.5) * 0.35

def city_noise(d):
    t = tvec(d)
    s = crowd(d) * 1.4
    # 喇叭：兩個方波和弦斷斷續續
    for t0, dur in ((0.1, 0.35), (0.6, 0.2), (0.9, 0.5), (1.55, 0.3)):
        tt = tvec(dur)
        h = (signal.square(2 * np.pi * 349 * tt) + signal.square(2 * np.pi * 440 * tt)) * 0.08
        h = lowpass(h, 2500) * env_ad(dur, 0.01)
        i = int(t0 * SR); s[i:i + len(h)] += h[: len(s) - i]
    # 施工：8 Hz 敲擊
    jack = bandpass(noise(d), 200, 1200) * (0.5 + 0.5 * signal.square(2 * np.pi * 8 * t)) * 0.3
    # 鬧鐘
    alarm = np.sin(2 * np.pi * 2100 * t) * (signal.square(2 * np.pi * 4 * t) > 0) * 0.07
    return s + jack + alarm

def shimmer():
    out = np.zeros(int(1.2 * SR))
    for k, m in enumerate((84, 88, 91, 96, 100)):
        b = bell(m, 0.9) * 0.5
        i = int(k * 0.06 * SR); out[i:i + len(b)] += b[: len(out) - i]
    return out

def rattle():
    t = tvec(0.9)
    return bandpass(noise(0.9), 1500, 6000) * (0.5 + 0.5 * np.sin(2 * np.pi * 22 * t)) ** 4 * np.exp(-t / 0.4) * 0.35

def fm_lead(m, d):
    """FM 數位主奏：載波＋2 倍頻調變，調變量隨時間衰減，帶一點滑音。"""
    t = tvec(d + 0.06)
    f = mtof(m) * (1 - 0.02 * np.exp(-t / 0.03))
    idx = 1.2 + 2.8 * np.exp(-t / 0.12)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph + idx * np.sin(2 * ph)) * 0.7 + signal.square(ph, 0.25) * 0.18
    e = np.minimum(1, t / 0.004) * np.where(t < d, 1.0, np.exp(-(t - d) / 0.05)) * (0.8 + 0.2 * np.exp(-t / 0.08))
    return lowpass(x, 7000) * e * 0.22

def saw_pluck(m, d=0.22, bright=1.0):
    t = tvec(d)
    f = mtof(m)
    x = sum((2 * ((f * k2 * t + rng.random()) % 1) - 1) * a for k2, a in ((1, 1.0), (1.005, 0.7)))
    cut = 600 + 7000 * bright * np.exp(-t / 0.05)
    y = np.zeros_like(x); z = 0.0
    al = 1 - np.exp(-2 * np.pi * cut / SR)
    for i in range(len(x)):
        z += al[i] * (x[i] - z); y[i] = z
    return y * np.exp(-t / 0.09) * 0.16

def supersaw(notes, d):
    t = tvec(d)
    L = np.zeros_like(t); R = np.zeros_like(t)
    for m in notes:
        for k, det in enumerate((-0.2, -0.1, -0.03, 0.03, 0.1, 0.2)):
            f = mtof(m) * 2 ** (det / 12)
            w = 2 * ((f * t + rng.random()) % 1) - 1
            if k % 2: L += w
            else: R += w
    st = np.stack([L, R], 1) * env_ad(d, 0.006, 0.18)[:, None]
    return lowpass(st, 5500) * 0.035

def sub_bass(m, d):
    t = tvec(d)
    f = mtof(m)
    ph = 2 * np.pi * f * t
    saw = 2 * ((f * t) % 1) - 1
    dark, bright = lowpass(saw, 380), lowpass(saw, 1300)
    x = np.sin(ph) * 0.8 + (dark + (bright - dark) * np.exp(-t / 0.06)) * 0.45
    return x * env_ad(d, 0.003, 0.3) * 0.6

def blip(m, d=0.06):
    """數位嗶聲（降位元）。"""
    t = tvec(d)
    x = signal.square(2 * np.pi * mtof(m) * t)
    x = np.round(x * np.exp(-t / 0.025) * 4) / 4
    return x * 0.09

def zap(d=0.35, f0=3000, f1=120):
    t = tvec(d)
    f = f1 + (f0 - f1) * np.exp(-t / (d / 4))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (d / 2)) * 0.35

def boot_up(d=2.0):
    """開機音：上升的數位琶音＋掃頻。"""
    out = np.zeros(int(d * SR))
    seq = [60, 64, 67, 72, 76, 79, 84, 88, 91, 96]
    for k, m in enumerate(seq):
        b = blip(m, 0.08) * (0.6 + 0.4 * k / len(seq))
        i = int(k * (d * 0.45) / len(seq) * SR); out[i:i + len(b)] += b[: len(out) - i]
    t = tvec(d)
    sweep = np.sin(2 * np.pi * np.cumsum(200 * 2 ** (4 * t / d)) / SR) * (t / d) ** 2 * 0.08
    return out + sweep

def glitch_stutter(x_src, t0, n=8, slice_=0.0625):
    """把 t0 起的一小段切片重複，做出 glitch 斷音。"""
    i = int(t0 * SR); L = int(slice_ * SR)
    piece = x_src[i:i + L].copy()
    for k in range(n):
        j = i + k * L
        x_src[j:j + L] = piece * (1 - 0.06 * k)

# ---------------------------------------------------------------- 編曲
CHORDS = [  # F – G – Em – Am（IV–V–iii–vi），收在 C
    dict(root=41, tones=(65, 69, 72, 77), stab=(65, 69, 72)),
    dict(root=43, tones=(67, 71, 74, 79), stab=(67, 71, 74)),
    dict(root=40, tones=(64, 67, 71, 76), stab=(64, 67, 71)),
    dict(root=45, tones=(69, 72, 76, 81), stab=(69, 72, 76)),
]
FINAL = dict(root=36, tones=(72, 76, 79, 84), stab=(72, 76, 79))
def chord(bar): return FINAL if bar >= 29 else CHORDS[bar % 4]
HOOK = [  # 每小節 (拍, 拍長, MIDI)：切分音記憶點
    [(0, .75, 79), (.75, .75, 77), (1.5, .5, 76), (2, .5, 72), (2.5, .5, 74), (3, 1, 76)],
    [(0, .75, 79), (.75, .75, 77), (1.5, .5, 76), (2, .5, 74), (2.5, .5, 71), (3, 1, 74)],
    [(0, .75, 79), (.75, .75, 81), (1.5, .5, 79), (2, .5, 76), (2.5, .5, 79), (3, 1, 83)],
    [(0, .5, 84), (.5, .5, 83), (1, .5, 81), (1.5, .5, 79), (2, 1, 76), (3, .5, 79), (3.5, .5, 81)],
]
VERSE = [  # 主歌：短促、像資料跳動
    [(0, .25, 72), (.5, .25, 72), (1, .25, 77), (1.5, .5, 76), (2.5, .25, 72), (3, .5, 74)],
    [(0, .25, 74), (.5, .25, 74), (1, .25, 79), (1.5, .5, 77), (2.5, .25, 74), (3, .5, 71)],
    [(0, .25, 71), (.5, .25, 71), (1, .25, 76), (1.5, .5, 74), (2.5, .25, 71), (3, .5, 79)],
    [(0, .25, 76), (.5, .25, 76), (1, .25, 81), (1.5, .5, 79), (2.5, .5, 76), (3, .5, 72), (3.5, .5, 74)],
]

music = Bus(); drums = Bus(); sfx = Bus(); amb = Bus()
kicks = []
def bars(a, b): return range(a, b)
QUIET = {19}   # 38–40 秒降噪後的一小節

# 主旋律：8–24 秒主歌、24–36 秒副歌、40–50 秒主歌、50–58 秒副歌高八度
for b in list(bars(4, 18)) + list(bars(20, 28)):
    chorus = 12 <= b < 18 or b >= 25
    phrase = (HOOK if chorus else VERSE)[b % 4]
    up = 12 if b >= 25 else 0
    for beat, d, m in phrase:
        music.add(b * BAR + beat * BEAT, fm_lead(m + up, d * BEAT * 0.9), 1.0 if chorus else 0.85, pan=0.05)
        if chorus:  # 副歌疊八度低音層
            music.add(b * BAR + beat * BEAT, fm_lead(m + up - 12, d * BEAT * 0.9), 0.45, pan=-0.05)
for beat, d, m in ((0, .5, 79), (.5, .5, 81), (1, .5, 83), (1.5, 2.5, 84)):  # 56–60 秒收尾句
    music.add(28 * BAR + beat * BEAT, fm_lead(m, d * BEAT * 0.9), 1.0, 0.05)
music.add(29 * BAR, fm_lead(84, 1.6), 1.0, 0.05)
music.add(29 * BAR, fm_lead(72, 1.6), 0.5, 0.05)

# 16 分音符鋸齒琶音（4 秒起）
for b in bars(2, 29):
    tones = chord(b)["tones"]
    seq = [0, 1, 2, 3, 2, 1, 2, 3] * 2
    lvl = 0.6 if b < 4 else (0.5 if b in QUIET else 1.0)
    bright = 0.4 if b in QUIET or b == 18 else 1.0
    for k in range(16):
        m = tones[seq[k]] + (12 if (k // 8) % 2 and b >= 12 else 0)
        music.add(b * BAR + k * BEAT / 4, saw_pluck(m, 0.2, bright), lvl, pan=-0.4 if k % 2 else 0.4)

# Supersaw 和弦：反拍短奏，副歌加長
for b in list(bars(4, 19)) + list(bars(20, 29)):
    st = chord(b)["stab"]
    chorus = 12 <= b < 18 or b >= 25
    hits = (0.5, 1.5, 2.5, 3.5) if not chorus else (0, 0.75, 1.5, 2.5, 3.25)
    if b >= 29: hits = (0,)
    for h in hits:
        d = 0.18 if not chorus else 0.3
        if b >= 29: d = 1.8
        music.add(b * BAR + h * BEAT, supersaw(st, d), 1.0 if not chorus else 1.3)

# 開場：0–4 秒開機音、低頻鋪底
music.add(0.0, pad((60, 67, 72), 4.0), 1.6)
sfx.add(0.9, boot_up(2.2), 0.9)

# 貝斯：sub＋鋸齒，8 分音符八度跳
for b in bars(2, 30):
    r = chord(b)["root"]
    if b >= 29:
        music.add(b * BAR, sub_bass(r, 1.8), 1.0); continue
    if b < 4:
        for k in (0, 2): music.add(b * BAR + k * BEAT, sub_bass(r, BEAT * 1.6), 0.8)
        continue
    if b in QUIET:
        music.add(b * BAR, sub_bass(r, BAR * 0.9), 0.6); continue
    for k in range(8):
        music.add(b * BAR + k * BEAT / 2, sub_bass(r + (12 if k % 2 else 0), BEAT * 0.42), 0.85)

# 鼓：four-on-the-floor、16 分 hi-hat、數位小打擊
def groove(b, level=1.0, extra=True):
    t0 = b * BAR
    for beat in range(4):
        drums.add(t0 + beat * BEAT, kick(), 1.0 * level); kicks.append(t0 + beat * BEAT)
    for beat in (1, 3):
        drums.add(t0 + beat * BEAT, clap(), 0.85 * level, pan=0.05)
        drums.add(t0 + beat * BEAT, snare(), 0.45 * level)
    for k in range(4): drums.add(t0 + (k + 0.5) * BEAT, hat(True), 0.6 * level, pan=0.3)
    if extra:
        for k in range(16):
            if k % 2: drums.add(t0 + k * BEAT / 4, hat(), 0.55 * level, pan=-0.3)
        for beat, m in ((0.75, 96), (1.75, 91), (2.75, 96), (3.25, 100)) if b % 2 else ((0.75, 96), (2.75, 103)):
            drums.add(t0 + beat * BEAT, blip(m), 1.0 * level, pan=0.5 if m > 96 else -0.5)
for b in bars(2, 4):
    groove(b, 0.75, extra=False)
    for k in range(16): drums.add(b * BAR + k * BEAT / 4, hat(), 0.4, pan=-0.3)
for b in bars(4, 18): groove(b)
for k in range(8):   # 36–38 秒噪音段：鼓悶住
    drums.add(36.0 + k * BEAT / 2, kick(0.6), 0.6); kicks.append(36.0 + k * BEAT / 2)
for b in bars(20, 28): groove(b)
for b in bars(25, 28):
    for k in (0.5, 1.5, 2.5, 3.5): drums.add(b * BAR + k * BEAT, clap(), 0.35, pan=-0.3)
for b in bars(12, 15):  # 樂團段觀眾拍手
    for k in (1.5, 3.5): drums.add(b * BAR + k * BEAT, clap(), 0.5, pan=-0.3)
for k in range(16):  # 39–40、49–50 秒小鼓滾奏
    drums.add(39.0 + k * BEAT / 8, snare(), 0.2 + 0.5 * k / 16)
    drums.add(49.0 + k * BEAT / 8, snare(), 0.25 + 0.6 * k / 16)
for t_ in (8.0, 24.0, 50.0):
    drums.add(t_, crash(2.2), 0.6)
drums.add(28 * BAR, kick(), 0.9); kicks.append(28 * BAR)
drums.add(29 * BAR, kick(), 1.0); kicks.append(29 * BAR)
drums.add(29 * BAR, crash(3.0), 0.6)

# 音效（對齊畫面）
sfx.add(1.0, case_click(False), 0.9)
sfx.add(6.7, whoosh(1.0), 0.6, pan=0.4)
sfx.add(11.4, whoosh(0.6), 0.7); sfx.add(12.0, zap(), 0.6)
for bb in TL["bubbles"]:
    sfx.add(bb["start"], pop_blip(), 0.6)
    sfx.add(bb["flip"], ding(), 0.55)
sfx.add(17.6, whoosh(0.5), 0.35); sfx.add(23.6, whoosh(0.5), 0.35)
sfx.add(29.7, whoosh(0.5), 0.4); sfx.add(36.0, zap(0.4, 1800, 200), 0.4); sfx.add(50.0, zap(0.5, 4000, 80), 0.6)
sfx.add(30.85, splash(), 1.0)
sfx.add(33.2, rattle(), 0.8)
sfx.add(34.4, shimmer(), 0.5)
sfx.add(36.0, city_noise(2.05), 0.9)
sfx.add(38.0, pop_blip(), 0.8); sfx.add(38.0, shimmer(), 0.4)
sfx.add(48.0, riser(2.0), 0.8); sfx.add(6.0, riser(2.0), 0.5); sfx.add(38.0, riser(2.0), 0.45)
sfx.add(50.0, crash(2.5), 0.7); sfx.add(50.0, kick(1.2), 0.9)
sfx.add(55.6, whoosh(0.9), 0.5, pan=-0.3)
sfx.add(58.0, case_click(True), 1.0)
amb.add(18.0, waves(6.2), 0.35)
amb.add(30.0, waves(6.0), 0.3)
amb.add(24.0, crowd(6.0), 0.6)
amb.add(12.0, crowd(6.0), 0.18)

# ---------------------------------------------------------------- 混音
def reverb_ir(d=1.8):
    t = tvec(d)
    ir = rng.standard_normal((len(t), 2)) * np.exp(-t / (d / 6.9))[:, None]
    ir = lowpass(ir, 5000)
    ir[0] = 0
    return ir / np.sqrt((ir ** 2).sum(0))[None, :] * 0.35

def apply_reverb(x, wet=0.2):
    ir = reverb_ir()
    y = np.stack([signal.fftconvolve(x[:, c], ir[:, c])[: len(x)] for c in range(2)], 1)
    return x + wet * y

def delay(x, dt, fb=0.3, mix=0.25):
    d = int(dt * SR); y = x.copy()
    for k in range(1, 4):
        y[d * k:] += x[: len(x) - d * k] * (fb ** k) * mix / fb
    return y

# 側鏈：貝斯/pad/琶音隨大鼓壓縮
sc = np.ones(N)
tt = np.arange(N) / SR
for k in kicks:
    i = int(k * SR); j = min(N, i + int(0.3 * SR))
    sc[i:j] = np.minimum(sc[i:j], 1 - 0.45 * np.exp(-(tt[i:j] - k) / 0.09))
m = music.x * sc[:, None]
m = delay(m, 0.75 * BEAT, 0.3, 0.18)
# 36–38 秒：噪音段音樂悶住，38 秒降噪啟動瞬間恢復
muff = lowpass(m, 450)
w = np.clip((tt - 35.9) / 0.1, 0, 1) * (1 - np.clip((tt - 38.0) / 0.05, 0, 1))
m = m * (1 - w[:, None] * 0.85) + muff * (w[:, None] * 0.85)
mix = apply_reverb(m, 0.22) + apply_reverb(drums.x, 0.06) + apply_reverb(sfx.x, 0.12) + amb.x
for t_ in (11.5, 23.5, 47.5):  # glitch 過門
    glitch_stutter(mix, t_, n=8, slice_=BEAT / 8)
mix = highpass(mix, 30)
mix = mix[: int(DUR * SR)]
fade = int(0.6 * SR)
mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 1.5
# 限幅
peak_target = 0.89
g = 1.0 / max(1e-9, np.percentile(np.abs(mix), 99.95)) * 0.75
mix *= g
mix = np.tanh(mix * 1.2) * peak_target

def write_wav(path, x):
    import wave
    x16 = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes(x16.tobytes())

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "music.wav")
write_wav(out, mix)
print("wrote", out, mix.shape, "peak", np.abs(mix).max())

# ---------------------------------------------------------------- 波形 + 頻譜檢查圖（剪點畫紅線、重拍畫灰線）
if len(sys.argv) > 2:
    from PIL import Image, ImageDraw
    W, H = 2400, 700
    img = Image.new("RGB", (W, H), (18, 18, 24)); d = ImageDraw.Draw(img)
    mono = mix.mean(1)
    spb = len(mono) // W
    for x in range(W):
        seg_ = mono[x * spb:(x + 1) * spb]
        hi, lo = seg_.max(), seg_.min()
        d.line([(x, 175 - hi * 160), (x, 175 - lo * 160)], fill=(120, 200, 255))
    f, t_, S = signal.spectrogram(mono, SR, nperseg=2048, noverlap=1024)
    S = 10 * np.log10(S[f < 8000] + 1e-12)
    S = np.clip((S - S.max() + 80) / 80, 0, 1)[::-1]
    spec = Image.fromarray((S * 255).astype(np.uint8)).resize((W, 330))
    spec = Image.merge("RGB", (spec, spec.point(lambda v: int(v * 0.6)), spec.point(lambda v: 255 - v if v > 0 else 0)))
    img.paste(spec, (0, 360))
    for b in range(31):
        x = int(b * BAR / DUR * W); d.line([(x, 0), (x, 350)], fill=(70, 70, 80))
    for s in TL["shots"]:
        x = int(s["start"] / DUR * W); d.line([(x, 0), (x, H)], fill=(255, 70, 70), width=2)
        d.text((x + 3, 4), f"#{s['id']}", fill=(255, 200, 200))
    img.save(sys.argv[2])
    print("wrote", sys.argv[2])
