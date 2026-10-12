"""Make the final demo video: captions burned in, played at 1.25x speed.

Captions come from docs/VOICEOVER_SCRIPT.md, timed against the voiced parts of each trimmed narration clip
(video_out/clips/sceneN.wav) at the scene starts in video_out/timings.json, both written by make_demo_video.py.

Output: video_out/claimpilot_demo_final.mp4 (+ .srt for YouTube captions).
"""

import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video_out"
LEAD = 0.3  # must match make_demo_video.LEAD
SPEED = 1.25
FONT = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 40)
MAX_W, MAX_WORDS = 1300, 14


def script_scenes() -> list[str]:
    text = (ROOT / "docs" / "VOICEOVER_SCRIPT.md").read_text()
    return [q for _, q in re.findall(r"\*\*Scene (\d) [^\n]*\n> ([^\n]+)", text)]


def chunks(text: str) -> list[str]:
    """Sentences, with long ones split at commas/colons into pieces of at most MAX_WORDS words."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        words = sent.split()
        while len(words) > MAX_WORDS:
            # cut near the middle of what's left (balanced lines), preferring a comma/colon within 3 words
            k = -(-len(words) // MAX_WORDS)
            target = round(len(words) / k)
            near = [
                i for i in range(target - 3, target + 4) if 0 < i < len(words) and words[i - 1][-1] in ",:;"
            ]
            cut = min(near, key=lambda i: abs(i - target)) if near else target
            out.append(" ".join(words[:cut]))
            words = words[cut:]
        out.append(" ".join(words))
    return out


def voiced(wav: Path) -> list[tuple[float, float]]:
    """Voiced spans (seconds) of a narration clip: 50 ms frames above noise floor + 25 dB, gaps < 0.25 s merged."""
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
        if w.getnchannels() > 1:
            x = x.reshape(-1, w.getnchannels()).mean(1)
    fr = int(0.05 * sr)
    n = len(x) // fr
    db = 20 * np.log10(np.sqrt((x[: n * fr].reshape(n, fr) ** 2).mean(1)) + 1e-9)
    on = db > np.percentile(db, 10) + 25
    spans, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        if not v and start is not None:
            spans.append([start * 0.05, i * 0.05])
            start = None
    if start is not None:
        spans.append([start * 0.05, n * 0.05])
    merged = [spans[0]]
    for a, b in spans[1:]:
        if a - merged[-1][1] < 0.25:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [tuple(s) for s in merged]


def timed(scene_start: float, wav: Path, text: str) -> list[tuple[float, float, str]]:
    """Spread caption chunks over the voiced time by character count, so pauses push captions along."""
    spans, parts = voiced(wav), chunks(text)
    talk = sum(b - a for a, b in spans)
    weights = [len(p) for p in parts]
    total = sum(weights)

    def at(frac: float) -> float:  # voiced-time fraction -> clip time
        left = frac * talk
        for a, b in spans:
            if left <= b - a:
                return a + left
            left -= b - a
        return spans[-1][1]

    out, acc = [], 0
    for p, w in zip(parts, weights, strict=True):
        a, acc = at(acc / total), acc + w
        b = at(acc / total)
        out.append((scene_start + LEAD + a, scene_start + LEAD + b + 0.25, p))
    for i in range(len(out) - 1):  # no overlaps
        out[i] = (out[i][0], min(out[i][1], out[i + 1][0]), out[i][2])
    return out


def card(text: str, path: Path) -> None:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if FONT.getlength(trial) > MAX_W and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    lines.append(cur)
    lh, pad = 54, 18
    width = int(max(FONT.getlength(line) for line in lines)) + 2 * pad + 8
    height = lh * len(lines) + 2 * pad - 6
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=12, fill=(26, 26, 23, 205))
    for i, line in enumerate(lines):
        d.text((width / 2, pad + i * lh), line, font=FONT, fill=(255, 255, 255, 255), anchor="ma")
    img.save(path)


def srt(caps: list[tuple[float, float, str]], path: Path, scale: float = 1.0) -> None:
    def ts(t: float) -> str:
        t /= scale
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(t * 1000 % 1000):03d}"

    path.write_text("".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(caps, 1)))


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main() -> None:
    src = OUT / "claimpilot_demo.mp4"
    starts = json.loads((OUT / "timings.json").read_text())["starts"]
    scenes = script_scenes()
    if len(scenes) != len(starts):
        raise SystemExit(f"script has {len(scenes)} scenes, video has {len(starts)}")
    caps = [
        c
        for i, (s, text) in enumerate(zip(starts, scenes, strict=True), 1)
        for c in timed(s, OUT / "clips" / f"scene{i}.wav", text)
    ]
    capdir = OUT / "captions"
    capdir.mkdir(exist_ok=True)
    ins, chain, last = [], [], "0:v"
    for i, (a, b, text) in enumerate(caps, 1):
        png = capdir / f"{i:03d}.png"
        card(text, png)
        ins += ["-i", str(png)]
        chain.append(f"[{last}][{i}:v]overlay=x=(W-w)/2:y=H-h-48:enable='between(t,{a:.2f},{b:.2f})'[v{i}]")
        last = f"v{i}"
    out = OUT / "claimpilot_demo_final.mp4"
    chain.append(f"[{last}]setpts=PTS/{SPEED},fps=30[v];[0:a]atempo={SPEED}[a]")
    ffmpeg(
        "-i", str(src), *ins, "-filter_complex", ";".join(chain), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    )  # fmt: skip
    srt(caps, out.with_suffix(".srt"), SPEED)
    print(f"{len(caps)} captions -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
