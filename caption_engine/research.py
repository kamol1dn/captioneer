"""Break a reference video down for study: download, cuts, keyframes,
transcript, and pacing numbers.

    python -m caption_engine.toolkit research <url-or-file> -o research/

Writes into ``<out>/<slug>/``:

    video.mp4        the source (downloaded with yt-dlp when given a URL)
    info.json        yt-dlp metadata (title, views, likes...), URLs only
    words.json       WhisperX-aligned words
    frames/          one keyframe per shot
    hook.jpg         strip of the first 3 seconds, every 0.5s
    contact.jpg      every shot's keyframe on one sheet, timestamped
    timeline.jpg     24 evenly spaced frames (motion-graphics videos often have no hard cuts)
    metrics.json     pacing numbers (cuts, shot length, WPM, pauses, hook)
    report.md        all of the above, readable

Cut detection is ffmpeg's scene-change score, so on motion-graphics videos a
"cut" means a big visual change, not necessarily an edit point.
"""
import json
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from .media import ffmpeg_bin, probe
from .transcriber import Word, load_words
from .toolkit import transcribe_media

_ROOT = Path(__file__).resolve().parent.parent
_FONT = _ROOT / "assets-fonts" / "monsterrat" / "Montserrat-VariableFont_wght.ttf"
MIN_SHOT = 0.15      # merge "shots" shorter than this (flashes, flicker)
PAUSE = 0.35         # a gap this long ends a transcript line
HOOK_SECONDS = 3.0
TIMELINE_FRAMES = 24


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def _slug(source: str) -> str:
    if _is_url(source):
        parts = [p for p in urlparse(source).path.split("/") if p]
        return re.sub(r"[^\w-]", "_", parts[-1] if parts else "video")
    return re.sub(r"[^\w-]", "_", Path(source).stem)


def _download(url: str, folder: Path, cookies_from_browser: Optional[str]) -> Path:
    ytdlp = shutil.which("yt-dlp")
    cmd = [ytdlp] if ytdlp else [sys.executable, "-m", "yt_dlp"]
    cmd += [url, "-o", str(folder / "video.%(ext)s"), "--no-playlist",
            "-f", "bv*+ba/b", "--merge-output-format", "mp4",
            "--write-info-json", "--no-warnings", "--quiet"]
    bundled = Path(ffmpeg_bin("ffmpeg"))
    if bundled.is_absolute():
        cmd += ["--ffmpeg-location", str(bundled.parent)]
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{proc.stderr[-2000:]}")
    info = folder / "video.info.json"
    if info.exists():
        info.replace(folder / "info.json")
    vids = sorted(folder.glob("video.*"))
    if not vids:
        raise RuntimeError("yt-dlp reported success but no video file was written")
    return vids[0]


def _scene_cuts(video: Path, threshold: float) -> List[float]:
    proc = subprocess.run(
        [ffmpeg_bin("ffmpeg"), "-nostdin", "-i", str(video), "-an",
         "-vf", f"scale=270:-2,select='gt(scene\\,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def _shots(cuts: List[float], duration: float) -> List[tuple]:
    bounds = [0.0]
    for c in cuts:
        if c - bounds[-1] >= MIN_SHOT and duration - c >= MIN_SHOT:
            bounds.append(c)
    bounds.append(duration)
    return list(zip(bounds[:-1], bounds[1:]))


def _grab(video: Path, t: float, out: Path, width: int = 360) -> Path:
    subprocess.run(
        [ffmpeg_bin("ffmpeg"), "-nostdin", "-y", "-v", "error", "-ss", f"{t:.3f}",
         "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out)],
        check=True)
    return out


def _font(size: int):
    try:
        return ImageFont.truetype(str(_FONT), size)
    except OSError:
        return ImageFont.load_default()


def _sheet(images: List[Path], labels: List[str], out: Path, cols: int) -> Path:
    thumbs = [Image.open(p).convert("RGB") for p in images]
    w, h = thumbs[0].size
    rows = -(-len(thumbs) // cols)
    sheet = Image.new("RGB", (cols * w, rows * (h + 34)), (16, 16, 20))
    draw, font = ImageDraw.Draw(sheet), _font(22)
    for i, (im, lab) in enumerate(zip(thumbs, labels)):
        x, y = (i % cols) * w, (i // cols) * (h + 34)
        sheet.paste(im.resize((w, h)), (x, y + 34))
        draw.text((x + 8, y + 5), lab, fill=(255, 220, 80), font=font)
    sheet.save(out, quality=88)
    return out


def _lines(words: List[Word]) -> List[tuple]:
    """Group words into readable transcript lines at pauses / sentence ends."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or nxt.start - w.end >= PAUSE or w.text[-1:] in ".?!":
            lines.append((cur[0].start, " ".join(x.text for x in cur)))
            cur = []
    return lines


def _mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def research_video(source: str, out_dir: str = "research", language: Optional[str] = "en",
                   model: str = "large-v3", scene_threshold: float = 0.3,
                   cookies_from_browser: Optional[str] = None) -> dict:
    folder = Path(out_dir) / _slug(source)
    (folder / "frames").mkdir(parents=True, exist_ok=True)

    cached = sorted(folder.glob("video.*"))
    if cached:
        video = cached[0]
    elif _is_url(source):
        video = _download(source, folder, cookies_from_browser)
    else:
        video = folder / f"video{Path(source).suffix}"
        if not video.exists():
            shutil.copy2(source, video)

    meta = probe(str(video))
    duration = meta["duration"] or 0.0
    info = {}
    if (folder / "info.json").exists():
        raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
        info = {k: raw.get(k) for k in ("title", "uploader", "channel", "upload_date",
                                         "view_count", "like_count", "comment_count",
                                         "webpage_url", "description")}

    # ── shots ───────────────────────────────────────────────────────────────
    shots = _shots(_scene_cuts(video, scene_threshold), duration)
    frames = [_grab(video, (a + b) / 2, folder / "frames" / f"shot_{i:02d}_{a:05.1f}s.jpg")
              for i, (a, b) in enumerate(shots)]
    _sheet(frames, [f"#{i} {a:.1f}s ({b - a:.1f}s)" for i, (a, b) in enumerate(shots)],
           folder / "contact.jpg", cols=6)
    hook_ts = [t / 2 for t in range(int(HOOK_SECONDS * 2) + 1) if t / 2 < duration]
    hook_frames = [_grab(video, t, folder / "frames" / f"hook_{t:.1f}s.jpg", width=270) for t in hook_ts]
    _sheet(hook_frames, [f"{t:.1f}s" for t in hook_ts], folder / "hook.jpg", cols=len(hook_frames))
    tl_ts = [duration * (i + 0.5) / TIMELINE_FRAMES for i in range(TIMELINE_FRAMES)]
    tl_frames = [_grab(video, t, folder / "frames" / f"tl_{i:02d}_{t:05.1f}s.jpg", width=270)
                 for i, t in enumerate(tl_ts)]
    _sheet(tl_frames, [f"{t:.1f}s" for t in tl_ts], folder / "timeline.jpg", cols=8)

    # ── transcript (cached: delete words.json to re-run) ────────────────────
    words: List[Word] = []
    words_json = folder / "words.json"
    if meta["has_audio"] and not words_json.exists():
        transcribe_media(str(video), language, model, str(words_json))
    if words_json.exists():
        words = load_words(str(words_json))

    lens = [b - a for a, b in shots]
    span = (words[-1].end - words[0].start) if words else 0
    gaps = [b.start - a.end for a, b in zip(words, words[1:])]
    metrics = {
        "source": source,
        "duration_s": round(duration, 2),
        "resolution": f"{meta['width']}x{meta['height']}",
        "fps": float(meta["fps"]) if meta["fps"] else None,
        "shots": len(shots),
        "avg_shot_s": round(statistics.mean(lens), 2) if lens else None,
        "median_shot_s": round(statistics.median(lens), 2) if lens else None,
        "cuts_per_10s": round(10 * (len(shots) - 1) / duration, 2) if duration else None,
        "first_cut_s": round(shots[1][0], 2) if len(shots) > 1 else None,
        "words": len(words),
        "wpm": round(len(words) / (span / 60), 1) if span else None,
        "first_word_s": round(words[0].start, 2) if words else None,
        "speech_coverage": round(span / duration, 2) if duration and span else None,
        "longest_pause_s": round(max(gaps), 2) if gaps else None,
        "pauses_over_0_7s": sum(1 for g in gaps if g > 0.7),
        "hook_text": " ".join(w.text for w in words if w.start < HOOK_SECONDS),
        **{k: info.get(k) for k in ("title", "uploader", "upload_date",
                                    "view_count", "like_count", "comment_count")},
    }
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── report ──────────────────────────────────────────────────────────────
    md = [f"# {info.get('title') or folder.name}", ""]
    if info:
        md += [f"{info.get('uploader') or ''} · {info.get('upload_date') or ''} · "
               f"{info.get('view_count')} views · {info.get('like_count')} likes · "
               f"{info.get('comment_count')} comments", ""]
    md += ["## Pacing", "", "| metric | value |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in metrics.items()
           if k not in ("source", "hook_text", "title", "uploader", "upload_date")]
    md += ["", "## Hook (first 3s)", "", f"> {metrics['hook_text'] or '(no speech)'}", "",
           "![hook](hook.jpg)", "", "## Transcript", ""]
    md += [f"`{_mmss(t)}` {line}" + "  " for t, line in _lines(words)] or ["(no speech)"]
    md += ["", "## Timeline", "", "![timeline](timeline.jpg)", "",
           "## Shots", "", "![contact](contact.jpg)", "", "| # | start | length | frame |", "|---|---|---|---|"]
    md += [f"| {i} | {_mmss(a)} | {b - a:.2f}s | frames/{f.name} |"
           for i, ((a, b), f) in enumerate(zip(shots, frames))]
    (folder / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {"folder": str(folder.resolve()), "report": str((folder / "report.md").resolve()),
            "contact_sheet": str((folder / "contact.jpg").resolve()),
            "hook_strip": str((folder / "hook.jpg").resolve()),
            "timeline": str((folder / "timeline.jpg").resolve()), "metrics": metrics}
