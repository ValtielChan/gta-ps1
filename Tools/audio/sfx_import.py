"""sfx_import: raw generated sound effects (ElevenLabs mp3, named <category>_<id>.mp3) -> game-ready clips
Assets/GTA/Sounds/SFX/<Category>_<NN>.ogg, read by GTA > Setup Audio In Open Scene (Editor/AudioSetup.cs).

    python -I Tools/audio/sfx_import.py <raw dir>

One-shots: leading silence trimmed, peak normalized to -1 dBFS, mono 32 kHz (PS1-ish, light). Loops (skid,
ambience): untouched timing (no trim, the generator made them seamless), normalized, kept stereo.
Needs ffmpeg on PATH.
"""
import os
import re
import subprocess
import sys

NAMES = {'crash': 'Crash', 'bump': 'Bump', 'pole': 'Pole', 'bodyhit': 'BodyHit', 'splat': 'Splat', 'bodyland': 'BodyLand',
         'scream_m': 'ScreamM', 'scream_f': 'ScreamF', 'shout': 'Shout', 'panic': 'Panic', 'horn': 'Horn',
         'skid': 'Skid', 'ambience': 'Ambience'}
LOOPS = {'skid', 'ambience'}
MAX = {'panic': 6.0, 'horn': 2.0}   # seconds kept of a one-shot (default 2.5), faded out over the last 0.3 s
OUT = os.path.join(os.path.dirname(__file__), '..', '..', 'Assets', 'GTA', 'Sounds', 'SFX')


def peak_db(path):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'volumedetect', '-f', 'null', '-'],
                       capture_output=True, text=True)
    m = re.search(r'max_volume: (-?[\d.]+) dB', r.stderr)
    return float(m.group(1)) if m else 0.0


def main(raw):
    os.makedirs(OUT, exist_ok=True)
    count = {}
    for f in sorted(os.listdir(raw)):
        m = re.match(r'(.+)_[A-Za-z0-9]{20}\.mp3$', f)
        if not m or m.group(1) not in NAMES:
            continue
        cat = m.group(1)
        count[cat] = count.get(cat, 0) + 1
        dst = os.path.join(OUT, '%s_%02d.ogg' % (NAMES[cat], count[cat]))
        src = os.path.join(raw, f)
        gain = -1.0 - peak_db(src)
        if cat in LOOPS:
            af, fmt = 'volume=%.2fdB' % gain, ['-ar', '44100']
        else:
            t = MAX.get(cat, 2.5)
            af = ('silenceremove=start_periods=1:start_threshold=-45dB,volume=%.2fdB,atrim=0:%.2f,afade=t=out:st=%.2f:d=0.3'
                  % (gain, t, t - 0.3))
            fmt = ['-ac', '1', '-ar', '32000']
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', src, '-af', af] + fmt +
                       ['-c:a', 'libvorbis', '-q:a', '5', dst], check=True)
        print(os.path.basename(dst), '<-', f)


if __name__ == '__main__':
    main(sys.argv[1])
