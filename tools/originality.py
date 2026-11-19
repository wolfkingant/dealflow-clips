#!/usr/bin/env python3
"""Originality pass for clip-brain (2026-11-19).

Why: TikTok Studio flagged our clips "not eligible for For You: Unoriginal, low-quality
content" (content "imported or copied from other sources without any new, creative edits").
Official ads/trailers re-posted with a caption on top match the brand's own upload and the
hundreds of other clippers posting the same file, so TikTok gives them 0 For You views.
Instagram (reposted-content downrank) and YouTube Shorts (reused content) do the same.

What this does to a finished 1080x1920 clip (audio is left untouched, so "original audio"
rules still hold, and nothing is added that names our account, so "no handle/logo" rules hold):
  1. Re-frames the clip as a card on a new background (blurred, re-graded copy of itself),
     so no frame of the output matches the source frame-for-frame.
  2. Camera motion: a 0.5 s punch-in at frame 0 (stops the 0:01 swipe-away), a slow push-in
     across the clip, and a beat punch every BEAT seconds.
  3. Colour grade (contrast/saturation/gamma) + light film grain.
  4. Progress bar along the bottom of the card.
  5. Optional HOOK text burned in for the first HOOK_S seconds (top of frame) when the clip
     has none.
Every render writes <out>.orig.json with the settings, and originality_check() measures how
close the output still is to the input (SSIM); the gate requires < MAX_SSIM.

Usage:
  python3 originality.py in.mp4 out.mp4 [--hook "TEXT"] [--seed N] [--accent RRGGBB]
  python3 originality.py --check out.mp4 in.mp4
"""
import argparse, json, os, random, re, subprocess, sys

FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf',
    os.path.expanduser('~/Library/Fonts/Poppins-Bold.ttf'),
    '/Library/Fonts/Poppins-Bold.ttf',
]
MAX_SSIM = 0.80      # output vs input, whole-frame; raw re-posts score ~0.95+
CARD_W, CARD_H = 940, 1672   # card size inside the 1080x1920 frame (keeps captions readable)


def font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return 'Sans'


def probe_duration(p):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'default=nw=1:nk=1', p], capture_output=True, text=True).stdout
    return float(out.strip())


def esc(t):
    return t.replace('\\', '\\\\').replace(':', '\\:').replace("'", "’").replace(',', '\\,').replace('%', '\\%')


def build_filter(dur, seed, accent, hook):
    rnd = random.Random(seed)
    beat = round(rnd.uniform(2.8, 3.6), 2)          # punch rhythm differs per clip
    push = round(rnd.uniform(0.025, 0.035), 3)        # slow push-in over the clip
    punch = round(rnd.uniform(0.025, 0.03), 3)       # beat punch size
    hue = round(rnd.uniform(-6, 6), 1)
    sat = round(rnd.uniform(1.10, 1.22), 2)
    con = round(rnd.uniform(1.04, 1.10), 2)
    gam = round(rnd.uniform(0.96, 1.02), 2)
    yoff = rnd.choice([0, 12, 24])                  # card position varies a little
    T = max(dur, 1.0)
    # zoom(t) <= ~1.07 so corner logos required by campaigns stay in frame: intro punch (1.07 -> 1 in 0.5 s) + slow push + alternating beat punch
    z = (f"1+{push}*it/{T:.3f}"
         f"+0.07*max(0\\,1-it/0.5)"
         f"+{punch}*mod(floor(it/{beat})\\,2)")
    x0 = (1080 - CARD_W) // 2
    y0 = (1920 - CARD_H) // 2 + yoff
    f = []
    f.append('[0:v]fps=30,format=yuv420p,split=2[a][b]')
    # background: blurred, darker, hue-shifted copy, slowly drifting zoom the other way
    f.append(f"[a]scale=1296:2304,boxblur=30:4,eq=brightness=-0.28:saturation={sat}:contrast=1.0,"
             f"hue=h={-hue},crop=1080:1920:x='108+40*sin(t/3)':y='192+60*cos(t/4)'[bg]")
    # card: zoompan for camera motion (2x supersampled to avoid jitter), graded
    f.append(f"[b]scale=1350:2400,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
             f"s={CARD_W}x{CARD_H}:fps=30,eq=contrast={con}:saturation={sat}:gamma={gam},hue=h={hue},"
             f"noise=alls=4,format=yuv420p[card]")
    # white edge + accent shadow around the card
    f.append(f"[bg]drawbox=x={x0+10}:y={y0+14}:w={CARD_W}:h={CARD_H}:color=0x{accent}@0.55:t=fill,"
             f"drawbox=x={x0-5}:y={y0-5}:w={CARD_W+10}:h={CARD_H+10}:color=white@0.92:t=fill[frame]")
    f.append(f"[frame][card]overlay={x0}:{y0}:shortest=1[c1]")
    # progress bar under the card
    f.append(f"[c1]drawbox=x={x0}:y={y0+CARD_H+18}:w={CARD_W}:h=10:color=white@0.25:t=fill,"
             f"drawbox=x={x0}:y={y0+CARD_H+18}:w='max(1\\,{CARD_W}*t/{T:.3f})':h=10:color=0x{accent}@0.95:t=fill[c2]")
    last = 'c2'
    if hook:
        f.append(f"[{last}]drawtext=fontfile={font()}:text='{esc(hook)}':fontsize=64:fontcolor=white:"
                 f"box=1:boxcolor=0x{accent}@0.95:boxborderw=22:x=(w-text_w)/2:y=150:"
                 f"enable='lt(t\\,3.2)'[c3]")
        last = 'c3'
    f.append(f"[{last}]format=yuv420p[vo]")
    settings = dict(beat=beat, push=push, punch=punch, hue=hue, sat=sat, contrast=con, gamma=gam,
                    card=[CARD_W, CARD_H], card_y_offset=yoff, accent=accent, hook=hook or '', seed=seed)
    return ';'.join(f), settings


def originality_check(out_p, in_p):
    """Mean SSIM between output and input (both 1080x1920). Lower = more transformed."""
    r = subprocess.run(['ffmpeg', '-v', 'info', '-i', out_p, '-i', in_p, '-lavfi',
                        '[0:v]fps=2,scale=270:480[a];[1:v]fps=2,scale=270:480[b];[a][b]ssim',
                        '-f', 'null', '-'], capture_output=True, text=True)
    m = re.findall(r'All:([0-9.]+)', r.stderr)
    return float(m[-1]) if m else None


def transform(in_p, out_p, hook=None, seed=None, accent='FF3B5C'):
    dur = probe_duration(in_p)
    seed = seed if seed is not None else abs(hash(os.path.basename(in_p))) % 100000
    fc, settings = build_filter(dur, seed, accent, hook)
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', in_p, '-filter_complex', fc,
           '-map', '[vo]', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-maxrate', '6M', '-bufsize', '12M',
           '-c:a', 'copy', '-movflags', '+faststart', '-t', f'{dur:.3f}', out_p]
    subprocess.run(cmd, check=True)
    ssim = originality_check(out_p, in_p)
    settings.update(source=os.path.basename(in_p), duration=round(dur, 2), ssim_vs_input=ssim,
                    passes=ssim is not None and ssim < MAX_SSIM)
    json.dump(settings, open(out_p + '.orig.json', 'w'), indent=1)
    return settings


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out', nargs='?')
    ap.add_argument('--hook'); ap.add_argument('--seed', type=int)
    ap.add_argument('--accent', default='FF3B5C')
    ap.add_argument('--check', action='store_true', help='inp=rendered, out=source: print SSIM')
    a = ap.parse_args()
    if a.check:
        s = originality_check(a.inp, a.out)
        print(json.dumps(dict(ssim=s, passes=s is not None and s < MAX_SSIM)))
        sys.exit(0 if s is not None and s < MAX_SSIM else 1)
    print(json.dumps(transform(a.inp, a.out, a.hook, a.seed, a.accent)))
