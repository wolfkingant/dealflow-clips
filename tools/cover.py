#!/usr/bin/env python3
"""Designed cover (thumbnail) for a clip + bake it into the first frames (2026-11-19).

TikTok personal accounts ignore custom covers sent through Metricool and use the video's
first frame, which for us was a blurry letterboxed frame with no text (profile grid = 0 views).
So: build a 1080x1920 cover (sharpest moment, tight crop, big headline inside the grid-safe
middle 3:4 area), then show it for the first COVER_S seconds of the video (audio keeps
playing) and pass the same JPG as videoThumbnailUrl for Instagram/YouTube.

Usage:
  python3 cover.py video.mp4 "HEADLINE TEXT" --accent F5B700 [--hl "WORDS TO HIGHLIGHT"] \
      [--at 3.2] --jpg cover.jpg --out video_with_cover.mp4
"""
import argparse, os, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

FONT = next((f for f in ['/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf',
                         os.path.expanduser('~/Library/Fonts/Poppins-Bold.ttf')] if os.path.exists(f)), None)
W, H = 1080, 1920
SAFE_TOP, SAFE_BOT = 250, 1670          # profile grid shows roughly this band (3:4 centre crop)
COVER_S = 0.35


def dur(p):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                                 'default=nw=1:nk=1', p], capture_output=True, text=True).stdout)


def grab(p, t):
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', p, '-frames:v', '1', f.name], check=True)
        im = Image.open(f.name).convert('RGB'); im.load()
    os.unlink(f.name)
    return im


def sharp_rows(im):
    g = np.asarray(im.convert('L').resize((270, 480)), dtype=np.float32)
    lap = np.abs(np.diff(g, axis=1)).mean(axis=1)            # per-row horizontal detail
    return lap


def content_band(im):
    """Rows that hold real (non-blurred) picture; our renders put 16:9 footage on a blurred bg."""
    lap = sharp_rows(im)
    thr = max(4.0, np.percentile(lap, 60))
    rows = np.where(lap > thr)[0]
    if len(rows) < 40:
        return 0, H
    # longest run allowing small gaps
    runs, s, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > 6:
            runs.append((s, prev)); s = r
        prev = r
    runs.append((s, prev))
    a, b = max(runs, key=lambda x: x[1] - x[0])
    return int(a * 4), int((b + 1) * 4)


def score(im):
    g = np.asarray(im.convert('L').resize((270, 480)), dtype=np.float32)
    detail = np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean()
    bright = g.mean()
    pen = 0 if 50 < bright < 210 else 20
    return detail - pen


def pick_frame(p, at=None):
    d = dur(p)
    if at is not None:
        return grab(p, at)
    best = None
    for t in np.linspace(0.6, max(0.7, d * 0.7), 8):
        im = grab(p, float(t))
        s = score(im)
        if best is None or s > best[0]:
            best = (s, im)
    return best[1]


def wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if draw.textlength(t, font=font) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    return lines


def make_cover(frame, headline, accent, hl='', band=None):
    acc = tuple(int(accent[i:i + 2], 16) for i in (0, 2, 4))
    a, b = band if band else content_band(frame)
    band = frame.crop((0, a, W, b))
    # background: blurred, dark version of the frame
    bg = frame.resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.35)
    # picture: band scaled to fill width, then centre-cropped to the picture window
    win_top, win_bot = 760, SAFE_BOT - 20
    win_h = win_bot - win_top
    scale = max(W / band.width, win_h / band.height) * 1.08     # slight zoom = tighter crop
    pic = band.resize((int(band.width * scale), int(band.height * scale)), Image.LANCZOS)
    x0 = (pic.width - W) // 2; y0 = max(0, (pic.height - win_h) // 2)
    pic = pic.crop((x0, y0, x0 + W, y0 + win_h))
    pic = ImageEnhance.Contrast(ImageEnhance.Color(pic).enhance(1.2)).enhance(1.08)
    bg.paste(pic, (0, win_top))
    d = ImageDraw.Draw(bg)
    d.rectangle((0, win_top - 10, W, win_top), fill=acc)
    # headline in the top of the safe area
    size = 132
    while True:
        font = ImageFont.truetype(FONT, size)
        lines = wrap(d, headline.upper(), font, W - 110)
        lh = int(size * 1.08)
        if (len(lines) <= 3 and lh * len(lines) <= win_top - SAFE_TOP - 40) or size < 70:
            break
        size -= 6
    y = SAFE_TOP + (win_top - SAFE_TOP - 30 - lh * len(lines)) // 2
    hlw = set(hl.upper().split())
    for ln in lines:
        # draw word by word so highlight words get the accent colour
        tw = d.textlength(ln, font=font); x = (W - tw) / 2
        for i, w in enumerate(ln.split()):
            col = acc if w.strip('?!.,') in hlw else (255, 255, 255)
            d.text((x, y), w, font=font, fill=col, stroke_width=8, stroke_fill=(0, 0, 0))
            x += d.textlength(w + ' ', font=font)
        y += lh
    return bg


def bake(video, cover_jpg, out):
    """Cover shown for COVER_S s at the start (audio untouched), then a quick fade into the video."""
    fc = (f"[1:v]scale={W}:{H},format=yuv420p,setsar=1[c];"
          f"[0:v][c]overlay=0:0:enable='lt(t,{COVER_S})'[v1];"
          f"[1:v]scale={W}:{H},format=yuva420p,colorchannelmixer=aa=1[c2];"
          f"[v1][c2]overlay=0:0:enable='between(t,{COVER_S},{COVER_S + 0.25})':"
          f"format=auto,format=yuv420p[vo]")
    # simple + robust: hard cut after COVER_S (fade made overlay alpha handling flaky)
    fc = (f"[1:v]scale={W}:{H},format=yuv420p,setsar=1[c];"
          f"[0:v][c]overlay=0:0:enable='lt(t,{COVER_S})',format=yuv420p[vo]")
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-loop', '1', '-i', cover_jpg,
                    '-filter_complex', fc, '-map', '[vo]', '-map', '0:a?', '-shortest',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-maxrate', '6M', '-bufsize', '12M',
                    '-c:a', 'copy', '-movflags', '+faststart', out], check=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('video'); ap.add_argument('headline')
    ap.add_argument('--accent', default='F5B700'); ap.add_argument('--hl', default='')
    ap.add_argument('--at', type=float); ap.add_argument('--src', help='pick the frame from this file instead')
    ap.add_argument('--band', help='y0:y1 rows of the frame to use as the picture')
    ap.add_argument('--jpg', required=True); ap.add_argument('--out')
    a = ap.parse_args()
    fr = pick_frame(a.src or a.video, a.at)
    make_cover(fr, a.headline, a.accent, a.hl, tuple(map(int, a.band.split(':'))) if a.band else None).save(a.jpg, quality=92)
    if a.out:
        bake(a.video, a.jpg, a.out)
    print(a.jpg, a.out or '')
