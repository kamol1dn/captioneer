"""Stock footage for the b-roll pass: from a finished download to an attached entry.

The split with the user is deliberate. Finding footage — reading a clip, searching,
choosing between near-identical shots — is the slow part and the part worth
handing over. The download itself is a click that licenses the item to a
project on the user's own subscription, and stock sites forbid doing that with
automated tools, so the user makes it. What happens after the click is this
module: find what arrived, show what it is, and put it on the right entry at the
right size and rate.

Matching downloads to placeholders cannot rely on names. A stock site's file
name, item title and URL slug are three different strings, often with nothing
in common beyond a word or two. So ``suggest`` proposes, and every proposal
comes with a frame strip of the file; whoever assigns looks at the strip.
"""
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caption_engine.media import ffmpeg_bin, probe

from .edl import BRoll, Clip, EDL
from .graphics import broll_frames
from .timebase import Timebase

VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mxf", ".webm", ".avi"}
# A rate this far from the sequence's is conformed on the way in; closer than
# this (30 in a 29.97 sequence) drifts by well under a frame over any b-roll.
_RATE_TOLERANCE = 0.01
_STOPWORDS = {"the", "a", "an", "of", "on", "in", "and", "with", "for", "to",
              "at", "by", "video", "stock", "footage", "vertical", "utc", "mov",
              "mp4", "4k", "hd", "uhd", "1080p", "2160p", "clip"}


# ── probing ──────────────────────────────────────────────────────────────────

def media_info(path) -> dict:
    """What the compiler and the XML need to know about a b-roll file."""
    info = probe(str(path))
    fps = info.get("fps")
    return {"width": info.get("width"), "height": info.get("height"),
            "fps": round(float(fps), 5) if fps else None,
            "duration": round(info["duration"], 3) if info.get("duration") else None,
            "has_audio": bool(info.get("has_audio"))}


def broll_file_meta(edl: EDL) -> Tuple[Dict[str, dict], List[str]]:
    """xmeml ``<file>`` metadata for every attached b-roll file, keyed by path.

    Without it the writer declares any unknown file as a sequence-sized clip
    with audio: a 4K stock shot claims to be 1440x2560 and a silent rendered
    graphic grows an empty audio channel. Entries attached before ``media`` was
    recorded are probed here instead.
    """
    tb = edl.timebase
    meta, warnings = {}, []
    for clip in edl.clips:
        h = clip.hook or {}
        if h.get("source") and Path(h["source"]).exists():
            # Rendered by us to the sequence's own size and rate, silent.
            meta[str(Path(h["source"]).resolve())] = {
                "width": edl.frame_size[0], "height": edl.frame_size[1],
                "has_video": True, "has_audio": False,
                "duration_frames": h.get("frames"),
            }
        for b in clip.broll:
            if not b.source:
                continue
            path = Path(b.source)
            if not path.exists():
                continue  # the validator already warns about missing sources
            m = b.media
            if not m or not m.get("width"):
                try:
                    m = media_info(path)
                except Exception as e:  # a bad probe must not block the export
                    warnings.append(f"clip {clip.id}: could not probe b-roll "
                                    f"{b.id!r} ({e}) — declared at sequence size")
                    continue
            meta[str(path.resolve())] = {
                "width": m.get("width") or edl.frame_size[0],
                "height": m.get("height") or edl.frame_size[1],
                "has_video": True,
                "has_audio": bool(m.get("has_audio")),
                "duration_frames": (tb.to_frames(m["duration"])
                                    if m.get("duration") else None),
            }
    return meta, warnings


# ── finding downloads ────────────────────────────────────────────────────────

def default_folders() -> List[Path]:
    return [Path.home() / "Downloads"]


def scan(folders: List[Path], since: float, unzip_into: Path) -> List[Path]:
    """Video files in ``folders`` modified after ``since`` (epoch seconds).

    Zips are opened and their videos extracted into ``unzip_into`` — some stock
    items arrive as a zip of several resolutions. In-progress downloads
    (.crdownload, .part, .tmp) are skipped, as is anything whose size is still
    changing: a half-written file probes as a shorter clip and would attach as
    one.
    """
    found = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            if not p.is_file() or p.stat().st_mtime < since:
                continue
            ext = p.suffix.lower()
            if ext in VIDEO_EXTS:
                found.append(p)
            elif ext == ".zip":
                found.extend(_unzip_videos(p, unzip_into))
    settled = []
    sizes = {p: p.stat().st_size for p in found}
    time.sleep(0.5)
    for p in found:
        if p.exists() and p.stat().st_size == sizes[p]:
            settled.append(p)
    return sorted(settled, key=lambda p: p.stat().st_mtime)


def _unzip_videos(zip_path: Path, dest: Path) -> List[Path]:
    out = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                name = Path(info.filename)
                if info.is_dir() or name.suffix.lower() not in VIDEO_EXTS:
                    continue
                if name.name.startswith("._"):  # macOS resource forks
                    continue
                target = dest / f"{zip_path.stem}__{name.name}"
                # Already extracted and attached: ``take`` moved it up into
                # broll/ under a clip prefix. Extracting again would list the
                # same shot as a fresh download on every scan.
                if any(p.name.endswith(f"__{target.name}")
                       for p in dest.parent.glob(f"*__{target.name}")):
                    continue
                if not target.exists():
                    dest.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                out.append(target)
    except zipfile.BadZipFile:
        pass  # still downloading, or not ours
    return out


def contact_sheet(path: Path, out: Path, duration: Optional[float]) -> Optional[Path]:
    """Three frames side by side — enough to tell a phone close-up from a city."""
    if not duration:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    inputs = []
    for frac in (0.15, 0.5, 0.85):
        inputs += ["-ss", f"{duration * frac:.3f}", "-i", str(path)]
    filt = ";".join(f"[{i}:v]scale=-2:360,setsar=1[f{i}]" for i in range(3))
    filt += ";[f0][f1][f2]hstack=3"
    try:
        subprocess.run([ffmpeg_bin("ffmpeg"), "-y", "-v", "error", *inputs,
                        "-filter_complex", filt, "-frames:v", "1", str(out)],
                       check=True, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return None
    return out if out.exists() else None


# ── matching ─────────────────────────────────────────────────────────────────

def _tokens(s: str) -> set:
    s = re.sub(r"\d{4}-\d{2}-\d{2}(-\d{2}){0,3}", " ", s.lower())  # timestamps
    words = re.findall(r"[a-z]+|\d+", s)
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


def _candidate_tokens(c: dict) -> set:
    slug = c.get("url", "").rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-[A-Z0-9]{6,8}$", "", slug)  # trailing item id
    return _tokens(slug) | _tokens(c.get("title", ""))


def pending_slots(edl: EDL) -> List[Tuple[Clip, BRoll]]:
    """Footage placeholders still waiting for a file, in timeline order."""
    out = []
    for clip in edl.clips:
        for b in sorted(clip.broll, key=lambda x: x.start):
            if b.kind == "footage" and not b.source:
                out.append((clip, b))
    return out


def suggest(files: List[Path], slots: List[Tuple[Clip, BRoll]]) -> List[dict]:
    """Propose file -> placeholder assignments. Proposals, not decisions.

    Name overlap with a slot's candidates first, greedily by best score; what
    is left pairs up in download order against slot order, since the shortlist
    is handed over in slot order and tends to be downloaded that way. Every
    proposal says how it was made so the order-based ones get a harder look.
    """
    pairs = []
    for fi, f in enumerate(files):
        ft = _tokens(f.stem)
        for si, (clip, b) in enumerate(slots):
            best = 0.0
            for c in b.candidates or []:
                ct = _candidate_tokens(c)
                if ft and ct:
                    best = max(best, len(ft & ct) / len(ft | ct))
            if best > 0:
                pairs.append((best, fi, si))
    used_f, used_s, out = set(), set(), []
    for score, fi, si in sorted(pairs, reverse=True):
        if score < 0.3 or fi in used_f or si in used_s:
            continue
        used_f.add(fi)
        used_s.add(si)
        clip, b = slots[si]
        out.append({"file": str(files[fi]), "clip_id": clip.id, "broll_id": b.id,
                    "how": f"name match ({score:.2f})"})
    rest_f = [i for i in range(len(files)) if i not in used_f]
    rest_s = [i for i in range(len(slots)) if i not in used_s]
    for fi, si in zip(rest_f, rest_s):
        clip, b = slots[si]
        out.append({"file": str(files[fi]), "clip_id": clip.id, "broll_id": b.id,
                    "how": "download order — check the frames"})
    return out


# ── attaching ────────────────────────────────────────────────────────────────

def conform(src: Path, tb: Timebase) -> Path:
    """Re-time a file to the sequence rate, keeping its full frame.

    The XML declares every file at the sequence rate and counts in/out in
    sequence frames. A 25fps shot declared as 29.97 plays at the wrong speed or
    lands its in-point in the wrong place, depending on how Premiere reconciles
    the two, and neither is visible until the export. Re-timing once on the way
    in removes the question. Picture is kept at full size so the editor can
    still reframe.
    """
    rate = f"{tb.fps.numerator}/{tb.fps.denominator}"
    out = src.with_name(f"{src.stem}__{float(tb.fps):.2f}fps.mp4")
    subprocess.run(
        [ffmpeg_bin("ffmpeg"), "-y", "-v", "error", "-i", str(src),
         "-vf", f"fps={rate}", "-c:v", "libx264", "-preset", "medium",
         "-crf", "14", "-pix_fmt", "yuv420p", "-an", str(out)],
        check=True, capture_output=True, timeout=1800)
    return out


def take(file: Path, dest_dir: Path, clip: Clip, b: BRoll, tb: Timebase,
         source_in: Optional[float] = None) -> dict:
    """Move a downloaded file into the episode and attach it to ``b``.

    Returns what happened, including anything the caller should pass on: a
    conform, or a file shorter than the entry it fills.
    """
    if b.kind != "footage":
        raise ValueError(f"b-roll {b.id!r} is {b.kind!r}; stock footage goes on "
                         f"footage entries")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{clip.id}_{b.id}__{file.name}"
    if file.resolve() != dest.resolve():
        shutil.move(str(file), str(dest))
    notes = []
    info = media_info(dest)
    used = dest
    if info["fps"] and abs(info["fps"] - float(tb.fps)) / float(tb.fps) > _RATE_TOLERANCE:
        used = conform(dest, tb)
        notes.append(f"conformed {info['fps']:g}fps -> {float(tb.fps):.3f}fps "
                     f"({used.name}); the original is kept beside it")
        info = media_info(used)

    _, frames = broll_frames(clip, tb, b)
    need = tb.to_seconds(frames)
    have = info["duration"] or 0.0
    if source_in is None:
        # Skip the first second where there is room: stock shots often open on
        # a camera settling or a fade, and the middle is the usable part.
        source_in = min(1.0, max(0.0, have - need))
    if have and source_in + need > have + 1e-3:
        notes.append(f"file is {have:.2f}s but the entry needs {need:.2f}s from "
                     f"{source_in:.2f}s — shorten the entry or pick a longer shot")

    b.source, b.source_in, b.status = str(used), round(source_in, 3), "attached"
    b.media, b.graphic = info, None
    return {"clip_id": clip.id, "broll_id": b.id, "path": str(used),
            "source_in": b.source_in, "seconds": round(need, 2),
            "size": f"{info['width']}x{info['height']}", "notes": notes}
