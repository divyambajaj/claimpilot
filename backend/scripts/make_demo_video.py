"""Record the narrated demo video (`make video`): the real app in replay mode, driven by Playwright, one scene per voice clip.

    uv run python backend/scripts/make_demo_video.py   # -> video_out/claimpilot_demo.mp4

Needs ffmpeg/ffprobe, Playwright Chromium and audio_raw_files/scene1..9.m4a. Re-record one clip and re-run; the
screen recording is redone so every scene stretches to its clip. Uses port 8090 and /tmp/cp_video.db only.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "audio_raw_files"
OUT = ROOT / "video_out"
PORT = 8090
BASE = f"http://127.0.0.1:{PORT}"
DB = Path("/tmp/cp_video.db")
LEAD, TAIL = 0.3, 0.6  # clip starts 0.3 s into its scene; scene lasts at least clip + 0.6 s
MAX_SPEEDUP = 1.4  # UI clicks and typing still read naturally up to this speed

CARD = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
html,body{{margin:0;height:100%;background:#FAFAF7;color:#1A1A17;font-family:"IBM Plex Sans",system-ui,sans-serif}}
main{{height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 150px}}
.rule{{width:42px;height:2px;background:#0F5B4E;margin-bottom:30px}}
h1{{font-size:{size}px;font-weight:600;letter-spacing:-0.025em;margin:0;line-height:1.15;max-width:1100px}}
p{{font-size:27px;color:#4A4A44;margin:18px 0 0;max-width:1000px;line-height:1.35}}
small{{display:block;margin-top:54px;font-size:17px;color:#7A7A72;letter-spacing:0.01em}}
</style></head><body><main><div class="rule"></div><h1>{title}</h1><p>{sub}</p><small>{foot}</small></main></body></html>"""

# a visible pointer: headless recordings have no cursor
CURSOR = """addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;left:-40px;top:-40px;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;'
    + 'background:rgba(15,91,78,.28);border:2px solid rgba(15,91,78,.85);pointer-events:none;z-index:2147483647;'
    + 'transition:transform .12s';
  document.body.appendChild(c);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => c.style.transform = 'scale(.7)', true);
  addEventListener('mouseup', () => c.style.transform = '', true);
});"""


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout)


def start_server() -> subprocess.Popen:
    dist, src = ROOT / "frontend/dist/index.html", ROOT / "frontend/src"
    if not dist.exists() or max(p.stat().st_mtime for p in src.rglob("*")) > dist.stat().st_mtime:
        subprocess.run(["npm", "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True)
    for p in DB.parent.glob(DB.name + "*"):
        p.unlink()
    env = os.environ | {
        "LLM_PROVIDER": "replay",
        "SEED_DEMO": "1",
        "REPLAY_DELAY_S": "1.2",
        "DATABASE_URL": f"sqlite:///{DB}",
    }
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", str(PORT)],
        cwd=ROOT,
        env=env,
    )
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{BASE}/api/health", timeout=1)
            return proc
        except OSError:
            if proc.poll() is not None:
                raise SystemExit("server exited") from None
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("server did not come up")


class Director:
    def __init__(self, page: Page):
        self.page, self.t0, self.scene_t0 = page, time.time(), 0.0

    def now(self) -> float:
        return time.time() - self.t0

    def at(self, t: float) -> None:
        """Wait until `t` seconds into the current scene."""
        rest = t - (self.now() - self.scene_t0)
        if rest > 0:
            self.page.wait_for_timeout(rest * 1000)

    def pause(self, s: float) -> None:
        self.page.wait_for_timeout(s * 1000)

    def center(self, loc: Locator) -> None:
        # scroll only the nearest scrolling panel: scrollIntoView also nudges the document and clips the header
        loc.evaluate("""e => { let p = e.parentElement;
          while (p && !(p.scrollHeight > p.clientHeight && /auto|scroll/.test(getComputedStyle(p).overflowY))) p = p.parentElement;
          if (!p) return; const r = e.getBoundingClientRect(), q = p.getBoundingClientRect();
          p.scrollBy({top: r.top - q.top - (q.height - r.height) / 2, behavior: 'smooth'}); }""")
        self.pause(0.7)

    def point(self, loc: Locator, scroll: bool = True) -> None:
        if scroll:
            self.center(loc)
        box = loc.bounding_box()
        self.page.mouse.move(box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2, steps=25)
        self.pause(0.35)

    def click(self, loc: Locator) -> None:
        self.point(loc)
        loc.click()
        self.pause(0.5)

    def type(self, loc: Locator, text: str) -> None:
        self.click(loc)
        loc.press_sequentially(text, delay=35)
        self.pause(0.4)

    def card(self, title: str, sub: str, foot: str = "", size: int = 100) -> None:
        self.page.set_content(
            CARD.format(title=title, sub=sub, foot=foot, size=size), wait_until="networkidle"
        )

    def glow(self, loc: Locator, on: bool = True) -> None:
        loc.evaluate(
            "(e, on) => { e.style.transition = 'box-shadow .3s'; "
            "e.style.boxShadow = on ? 'inset 3px 0 0 #0F5B4E, 0 0 0 1px rgba(15,91,78,.35)' : '' }",
            on,
        )


def line(page: Page, text: str) -> Locator:
    return page.get_by_test_id("line-item").filter(has_text=text).first


def scene1(d: Director, dur: float) -> None:
    d.card(
        "ClaimPilot", "An AI assistant for expense claims", "Jio AI Innovation Lab · Season 2 · Divyam Bajaj"
    )


def scene2(d: Director, dur: float) -> None:
    d.page.goto(BASE, wait_until="networkidle")
    d.pause(1.5)
    d.point(d.page.get_by_role("button", name="Try sample receipts"), scroll=False)


def scene3(d: Director, dur: float) -> None:
    p = d.page
    d.at(dur * 0.3)
    d.click(p.get_by_role("button", name="Try sample receipts"))
    add = p.get_by_role("button", name="Add 13 to claim")
    add.wait_for()
    d.pause(1.0)
    d.point(p.get_by_role("dialog").locator("li").nth(4), scroll=False)
    d.at(dur * 0.62)
    d.click(add)
    p.get_by_text("13 documents read").wait_for(timeout=120_000)
    d.pause(1.5)


def scene4(d: Director, dur: float) -> None:
    p = d.page
    steps = [
        (0.42, "Harbourview", "proof-row"),
        (0.55, "Fort Stationery", "block-reason"),
        (0.68, "Rohan Desai", "block-reason"),
    ]
    d.point(p.get_by_role("region", name="Claim").get_by_role("heading"))
    prev = None
    for frac, name, part in steps:
        d.at(dur * frac)
        if prev:
            d.glow(prev, False)
        prev = line(p, name)
        d.center(prev)
        d.glow(prev)
        d.point(prev.get_by_test_id(part), scroll=False)
    d.at(dur * 0.8)
    d.glow(prev, False)
    meal = line(p, "Chaiwala")
    d.center(meal)
    d.glow(meal)
    d.pause(1.5)
    d.at(dur * 0.84)
    d.click(meal.get_by_role("button", name="Why?").first)
    d.at(dur + TAIL + 1.0)  # keep the policy quote up a beat after the narration
    d.click(p.get_by_role("dialog").get_by_role("button", name="Close"))
    d.glow(meal, False)


def scene5(d: Director, dur: float) -> None:
    p = d.page
    form = p.get_by_role("form", name="Questions")
    d.center(form)
    date = form.locator("input[type=date]")
    d.point(date, scroll=False)
    date.fill("2026-10-06")
    d.pause(0.6)
    d.click(form.get_by_role("radio", name="Same expense, drop it"))
    note = form.locator("textarea")
    d.at(dur * 0.45)
    d.type(note, "no reason")
    d.click(form.get_by_role("button", name="Send answers"))
    form.get_by_role("alert").wait_for()
    d.pause(2.5)
    note.fill("")
    d.type(note, "Client dinner approved in advance by the department head.")
    d.click(form.get_by_role("button", name="Send answers"))
    trip = p.get_by_role("form", name="Questions").locator("textarea, input[type=text]").last
    p.get_by_text("One more question").wait_for(timeout=60_000)
    d.pause(1.0)
    d.type(trip, "Drove to the Thane client site and back on 6 Oct for the workshop.")
    d.click(p.get_by_role("form", name="Questions").get_by_role("button", name="Send answers"))
    p.get_by_text("All lines are complete").first.wait_for(timeout=60_000)
    d.center(p.get_by_text("All lines are complete").first)
    d.pause(1.5)


def scene6(d: Director, dur: float) -> None:
    p = d.page
    claim = p.get_by_role("region", name="Claim")
    d.click(claim.get_by_role("button", name="Submit claim"))
    claim.get_by_text("Reference").wait_for(timeout=30_000)
    d.point(claim.get_by_text("Reference"), scroll=False)
    d.at(dur * 0.4)
    d.click(claim.get_by_role("button", name="Raise a ticket with Finance"))
    form = claim.get_by_role("form", name="Raise a ticket")
    for box in form.locator("label:has(input[type=checkbox])").all():
        if "Rohan" not in box.inner_text():
            d.click(box.locator("input"))
    d.type(
        form.locator("#ticket-note"),
        "Shared cab with a colleague to the client site; I paid him back by UPI.",
    )
    d.click(form.get_by_role("button", name="Submit ticket"))
    pill = claim.get_by_test_id("ticket-pill").first
    pill.wait_for(timeout=30_000)
    d.point(pill)
    d.pause(1.5)


def scene7(d: Director, dur: float) -> None:
    p = d.page
    p.goto(f"{BASE}/#/admin/overview", wait_until="networkidle")
    d.pause(1.5)
    p.mouse.move(820, 420, steps=20)
    d.at(dur * 0.32)  # KPI tiles stay in view while they are named
    for _ in range(4):
        d.pause(1.5)
        p.mouse.wheel(0, 260)
    d.at(dur * 0.6)
    p.mouse.wheel(0, -4000)
    d.click(p.get_by_role("navigation", name="Admin").get_by_role("link", name="Traces"))
    p.get_by_text("spans").first.wait_for()
    d.pause(1.0)
    items = p.locator("li > button").filter(has_text="spans")
    counts = [int(t.split("·")[-1].split()[0]) for t in items.all_inner_texts()]
    d.click(items.nth(counts.index(max(counts))))
    d.pause(2.0)
    p.mouse.move(900, 450, steps=30)


def scene8(d: Director, dur: float) -> None:
    p = d.page
    d.click(p.get_by_role("navigation", name="Admin").get_by_role("link", name="Evaluation"))
    sel = p.locator("select").first
    sel.wait_for()
    value = sel.evaluate(
        "s => ([...s.options].find(o => o.text.includes('· full ·') && o.text.includes('· v3 ·')) || s.options[0]).value"
    )
    if sel.input_value() != value:
        d.point(sel, scroll=False)
        sel.select_option(value)
    d.pause(2.0)
    p.mouse.move(820, 450, steps=20)
    for _ in range(10):
        d.pause(max(1.0, (dur - 6) / 12))
        p.mouse.wheel(0, 220)


def scene9(d: Director, dur: float) -> None:
    p = d.page
    d.click(p.get_by_role("navigation", name="Admin").get_by_role("link", name="Policy"))
    marks = p.locator("mark")
    marks.first.wait_for()
    d.pause(1.5)
    for i, frac in ((0, 0.15), (len(marks.all()) // 2, 0.35)):
        d.at(dur * frac)
        d.point(marks.nth(i))
        d.pause(1.5)
    d.at(dur - 8)
    d.card(
        "ClaimPilot",
        "From a pile of bills to a claim that's ready to submit.",
        "github.com/divyambajaj/claimpilot",
        size=84,
    )


SCENES = [scene1, scene2, scene3, scene4, scene5, scene6, scene7, scene8, scene9]


def record(durs: list[float]) -> tuple[Path, list[float], float]:
    """Drive the scenes; frames come from a CDP screencast (Playwright's recorder ignores device_scale_factor)."""
    raw = OUT / "raw"
    shutil.rmtree(raw, ignore_errors=True)
    raw.mkdir(parents=True)
    frames: list[tuple[float, Path]] = []
    starts = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # 1440x810 CSS at 4/3 scale = 1080p frames with UI text large enough to read in the video
        ctx = browser.new_context(viewport={"width": 1440, "height": 810}, device_scale_factor=4 / 3)
        ctx.add_init_script(CURSOR)
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)

        def on_frame(f: dict) -> None:
            path = raw / f"{len(frames):06d}.jpg"
            path.write_bytes(base64.b64decode(f["data"]))
            frames.append((f["metadata"]["timestamp"], path))
            cdp.send("Page.screencastFrameAck", {"sessionId": f["sessionId"]})

        cdp.on("Page.screencastFrame", on_frame)
        page.set_content("<body style='background:#FAFAF7'>")
        cdp.send(
            "Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080}
        )
        d = Director(page)
        try:
            for i, (scene, dur) in enumerate(zip(SCENES, durs, strict=True), 1):
                d.scene_t0 = d.now()
                starts.append(d.scene_t0)
                scene(d, dur)
                d.at(dur + TAIL)
                print(
                    f"scene{i}: start {d.scene_t0:6.1f}s span {d.now() - d.scene_t0:5.1f}s clip {dur:5.1f}s",
                    flush=True,
                )
        finally:
            total = d.now()
            page.screenshot(path=str(OUT / "last.png"))
            ctx.close()
            browser.close()
    # Scenes whose clicks outran the narration are played faster (up to MAX_SPEEDUP) so there is no dead air.
    spans = [b - a for a, b in zip(starts, [*starts[1:], total], strict=True)]
    fits = [min(s, max(dur + TAIL + 0.3, s / MAX_SPEEDUP)) for s, dur in zip(spans, durs, strict=True)]
    new_starts = [sum(fits[:i]) for i in range(len(fits))]

    def remap(t: float) -> float:
        i = max(k for k, s in enumerate(starts) if s <= t) if t >= starts[0] else 0
        return new_starts[i] + (t - starts[i]) * fits[i] / spans[i]

    for i, (s, f) in enumerate(zip(spans, fits, strict=True), 1):
        if f < s:
            print(f"scene{i}: sped up {s / f:.2f}x ({s:.1f}s -> {f:.1f}s)", flush=True)
    # concat list: each frame holds until the next one; the first is stretched back to t0
    lst = raw / "frames.txt"
    times = [0.0] + [remap(ts - d.t0) for ts, _ in frames[1:]] + [sum(fits)]
    starts, total = new_starts, sum(fits)
    lst.write_text(
        "".join(
            f"file '{p.name}'\nduration {max(times[i + 1] - times[i], 0.001):.4f}\n"
            for i, (_, p) in enumerate(frames)
        )
        + f"file '{frames[-1][1].name}'\n"
    )
    return lst, starts, total


def render(frames: Path, starts: list[float], total: float, clips: list[Path]) -> Path:
    ins, mix = [], []
    for i, (clip, s) in enumerate(zip(clips, starts, strict=True), 1):
        ins += ["-i", str(clip)]
        mix.append(f"[{i}:a]aresample=48000,highpass=f=80,adelay={int((s + LEAD) * 1000)}:all=1[a{i}]")
    n = len(clips)
    fade = f"st={total - 0.4:.2f}:d=0.4"
    graph = (
        ";".join(mix)
        + ";"
        + "".join(f"[a{i}]" for i in range(1, n + 1))
        + (
            f"amix=inputs={n}:normalize=0:duration=longest,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
            f"apad,afade=in:d=0.4,afade=out:{fade}[a];"
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1:color=0xFAFAF7,setsar=1,"
            f"fps=30,format=yuv420p,fade=in:d=0.4,fade=out:{fade}[v]"
        )
    )
    out = OUT / "claimpilot_demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-i",
            str(frames),
            *ins,
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{total:.2f}",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    return out


def trim(clip: Path) -> Path:
    """Cut the silence the speaker left at both ends down to ~0.2 s so scenes don't drag."""
    out = OUT / "clips" / f"{clip.stem}.wav"
    out.parent.mkdir(exist_ok=True)
    edge = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.2"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-af",
            f"{edge},areverse,{edge},areverse",
            str(out),
        ],
        check=True,
    )
    return out


def main() -> None:
    raw_clips = [AUDIO / f"scene{i}.m4a" for i in range(1, 10)]
    if missing := [c.name for c in raw_clips if not c.exists()]:
        raise SystemExit(f"missing clips: {missing}")
    OUT.mkdir(exist_ok=True)
    clips = [trim(c) for c in raw_clips]
    durs = [duration(c) for c in clips]
    server = start_server()
    try:
        frames, starts, total = record(durs)
    finally:
        server.terminate()
        server.wait(10)
    (OUT / "timings.json").write_text(json.dumps({"starts": starts, "clips": durs}, indent=1))
    out = render(frames, starts, total, clips)
    print(f"{out} ({duration(out):.1f} s)")


if __name__ == "__main__":
    sys.exit(main())
