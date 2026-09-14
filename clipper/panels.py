"""Long-form panel graphics: a plan of timed graphics -> files + one XML timeline.

The OTG long-form layouts are 4K PNG frames with transparent panes. Graphics
for those panes are rendered at the pane's own size (never a 4K canvas with
padding), so the editor drops them on a track, sets Position once, and pastes
that Motion onto every other clip on the track:

    news  layout (``angle v1_1 (2).png``): middle pane -> V8
    guest layout (``angle V4.png``):       right pane  -> V9

A plan is JSON:

    {"name": "OTG EP19 panels",
     "video": "D:/.../main_1.mp4",          # the long-form render (timing + reference)
     "out_dir": "D:/.../longform/panels",
     "shots_dir": "D:/.../longform/shots",  # screenshots from shoot.py (+ .json)
     "items": [{"id": "n01", "layout": "news", "start": 8.6, "end": 22.4,
                "template": "PShot", "shot": "tc_muse",
                "marks": [{"phrase": 0, "style": "marker", "at_s": 14.5}],
                "props": {...}}]}

``start``/``end`` are seconds on the long-form timeline. A PShot item may name
a ``shot``; its image size and the page rectangles of each marked phrase come
from the shot's JSON, mark times are given in timeline seconds (``at_s``), and
the scroll is worked out so every mark is in view when it draws.

    python -m clipper.panels render plan.json [--only n01,n02] [--checks]
    python -m clipper.panels xml plan.json [more_plans.json ...]
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from .graphics import GRAPHICS_DIR, STAGED_DIR, ensure_installed
from .timebase import Timebase
from .xmeml.pathurl import to_pathurl

FPS = Timebase(30, ntsc=True)
TRANSITION_FRAMES = 4  # the long-form layouts cross-fade over 4 frames
# Premiere's tick rate, for the transitions' cutPointTicks.
TICKS_PER_SECOND = 254016000000

BRAND = Path(r"D:\gashtak work\OTG\brand assets")
# Pane geometry measured off the layout PNGs (transparent rectangle, 4K).
# Renders carry a few px of bleed each side; the frame border is opaque for
# 7+ px around both panes, so the bleed is hidden and a half-pixel of
# misalignment can never open a hairline gap. Sizes are even for the codecs.
LAYOUTS = {
    "news": {"pane": (944, 0, 1953, 1520), "size": (1960, 1528), "track": 8,
             "png": BRAND / "angle v1_1 (2).png"},
    "guest": {"pane": (960, 167, 2791, 1350), "size": (2800, 1360), "track": 9,
              "png": BRAND / "angle V4.png"},
}
SEQ_SIZE = (3840, 2160)
IMAGE_PROPS = ("image", "logo", "photo")


def position(layout: str):
    """Premiere Motion > Position that centres a render on its pane."""
    x, y, w, h = LAYOUTS[layout]["pane"]
    return (x + w / 2, y + h / 2)


# ── planning ────────────────────────────────────────────────────────────────


def load(plan_path) -> dict:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    plan["_dir"] = str(Path(plan_path).parent)
    return plan


def frames_of(item: dict):
    s = FPS.to_frames(item["start"])
    e = FPS.to_frames(item["end"])
    return s, e


def _stage(props: dict) -> dict:
    out = dict(props)
    for key in IMAGE_PROPS:
        p = props.get(key)
        if not p or str(p).startswith(("http://", "https://", "data:", "_assets/")):
            continue
        src = Path(p)
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
        STAGED_DIR.mkdir(parents=True, exist_ok=True)
        dest = STAGED_DIR / f"{digest}{src.suffix.lower()}"
        if not dest.exists():
            shutil.copyfile(src, dest)
        out[key] = f"_assets/{dest.name}"
    return out


def _shot_props(plan: dict, item: dict) -> dict:
    """Fill a PShot's image, size, marks and scroll from its screenshot."""
    shots = Path(plan.get("shots_dir") or Path(plan["_dir"]) / "shots")
    meta = json.loads((shots / f"{item['shot']}.json").read_text(encoding="utf-8"))
    props = dict(item.get("props", {}))
    props.setdefault("image", str(shots / f"{item['shot']}.png"))
    props["imgW"], props["imgH"] = meta["imgW"], meta["imgH"]
    dur = item["end"] - item["start"]

    marks = []
    blocks = []
    for m in item.get("marks", []):
        ph = meta["marks"][m["phrase"]] if isinstance(m["phrase"], int) else \
            next(x for x in meta["marks"] if x["phrase"] == m["phrase"])
        if ph.get("block"):
            blocks.append(ph["block"])
        if not ph["rects"]:
            raise ValueError(f"{item['id']}: phrase not on the page: {ph['phrase']!r}")
        at = (m["at_s"] - item["start"]) / dur
        for j, r in enumerate(ph["rects"]):
            # Multi-line phrases draw line after line, like a pen would.
            marks.append({**r, "style": m.get("style", "marker"), "at": round(at + j * 0.5 / dur, 4)})
    props["marks"] = marks

    # "crop": "auto" zooms onto the text column the marks sit in, so body text
    # reads at 4K instead of being a whole desktop page shrunk into the pane.
    if props.pop("crop", None) == "auto" and marks:
        # Whole paragraphs when the shot recorded them; else just the marks.
        spans = [(bk["x"], bk["x"] + bk["w"]) for bk in blocks] or \
            [(m["x"], m["x"] + m["w"]) for m in marks]
        left = min(a for a, _ in spans)
        right = max(b for _, b in spans)
        pad = 0.03 if blocks else 0.04
        x0, x1 = max(0.0, left - pad), min(1.0, right + pad)
        if x1 - x0 < 0.5:  # never zoom past 2x
            mid = (x0 + x1) / 2
            x0, x1 = max(0.0, mid - 0.25), min(1.0, mid + 0.25)
        props["x0"], props["x1"] = round(x0, 4), round(x1, 4)

    # Scroll so the marks are in view when they draw.
    W, H = LAYOUTS[item["layout"]]["size"]
    u = H / 1000
    x0, x1 = props.get("x0", 0), props.get("x1", 1)
    win_w = W - 92 * u
    view_h = H - 92 * u - 64 * u - (154 * u if props.get("caption") else 0)
    k = win_w / ((x1 - x0) * meta["imgW"])
    view = view_h / (meta["imgH"] * k)          # visible fraction of the image
    lim = max(0.0, 1 - view)
    clamp = lambda v: round(min(lim, max(0.0, v)), 4)
    from_top = props.pop("from_top", False)
    if marks and "y0" not in props and "path" not in props:
        props["path"] = _scroll_path(marks, view, clamp, dur, from_top)
    return _precrop(props, item, view, shots)


def _precrop(props: dict, item: dict, view: float, shots: Path) -> dict:
    """Cut the screenshot down to the part the pane will ever show.

    A full-page capture is ~2880x8000 px and Chrome composites all of it every
    frame, which is what makes page renders ~6x slower than text panels. The
    crop keeps the visible column across the whole scroll range (plus the view
    height below its lowest point) and remaps marks and scroll to match.
    """
    from PIL import Image

    W0, H0 = props["imgW"], props["imgH"]
    x0, x1 = props.get("x0", 0.0), props.get("x1", 1.0)
    if props.get("path"):
        tops = [y for _, y in props["path"]]
    else:
        tops = [props.get("y0", 0.0), props.get("y1", props.get("y0", 0.0))]
    ya = max(0.0, min(tops))
    yb = min(1.0, max(tops) + view * 1.02)
    if x1 - x0 > 0.98 and yb - ya > 0.98:
        return props
    box = (round(x0 * W0), round(ya * H0), round(x1 * W0), round(yb * H0))
    src = Path(props["image"])
    out_dir = shots / "_crops"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{item['id']}.png"
    Image.open(src).crop(box).save(out)
    nw, nh = box[2] - box[0], box[3] - box[1]
    fx = lambda v: (v * W0 - box[0]) / nw
    fy = lambda v: (v * H0 - box[1]) / nh
    props = dict(props, image=str(out), imgW=nw, imgH=nh, x0=0.0, x1=1.0)
    props["marks"] = [dict(m, x=fx(m["x"]), y=fy(m["y"]), w=m["w"] * W0 / nw, h=m["h"] * H0 / nh)
                      for m in props.get("marks", [])]
    if props.get("path"):
        props["path"] = [(t, round(fy(y), 5)) for t, y in props["path"]]
    for k in ("y0", "y1"):
        if k in props:
            props[k] = round(fy(props[k]), 5)
    return props


def _scroll_path(marks, view, clamp, dur, from_top):
    """Keyframes that travel from mark to mark, arriving just before each draws.

    A phrase already comfortably in view doesn't move the page; one that isn't
    scrolls in over up to 1.5 s. The last stretch keeps drifting a little, so
    the page is never frozen.
    """
    # One group per phrase: its lines are consecutive rects a moment apart.
    by_phrase = []
    for m in sorted(marks, key=lambda m: m["at"]):
        if by_phrase and m["at"] - by_phrase[-1]["at"] < 0.6 / dur + 1e-6 and \
                abs(m["y"] - by_phrase[-1]["y1"]) < 0.02:
            g = by_phrase[-1]
            g["y1"] = max(g["y1"], m["y"] + m["h"])
        else:
            by_phrase.append({"at": m["at"], "y0": m["y"], "y1": m["y"] + m["h"]})
    top = lambda g: clamp((g["y0"] + g["y1"]) / 2 - 0.42 * view)
    cur = 0.0 if from_top else top(by_phrase[0])
    kf = [(0.0, cur)]
    for g in by_phrase:
        centre = (g["y0"] + g["y1"]) / 2
        if cur + 0.12 * view <= centre <= cur + 0.85 * view:
            continue  # already readable where it is
        tgt = top(g)
        arrive = max(kf[-1][0] + 0.03, g["at"] - 0.02)
        leave = max(kf[-1][0] + 0.01, arrive - min(0.35, 1.5 / dur))
        kf += [(leave, cur), (arrive, tgt)]
        cur = tgt
    kf.append((1.0, clamp(cur + 0.04 * view)))
    # Strictly increasing times, as interpolate() requires.
    out = []
    for t, y in kf:
        t = min(1.0, max(t, out[-1][0] + 0.001 if out else 0.0))
        out.append((round(t, 4), y))
    return out


def build_jobs(plan: dict, only: Optional[List[str]] = None, codec: str = "h264"):
    out_dir = Path(plan["out_dir"])
    jobs = []
    for n, item in enumerate(plan["items"], start=1):
        if only and item["id"] not in only:
            continue
        s, e = frames_of(item)
        W, H = LAYOUTS[item["layout"]]["size"]
        props = _shot_props(plan, item) if item.get("shot") else dict(item.get("props", {}))
        if item.get("reveal_s"):
            # Cards / stops / steps land on the words that name them.
            dur = item["end"] - item["start"]
            props["reveal"] = [None if t is None else round((t - item["start"]) / dur, 4)
                               for t in item["reveal_s"]]
        props = _stage(props)
        out = out_dir / f"{item['id']}_{item['layout']}.mp4"
        jobs.append({"id": item["id"], "template": item["template"], "props": props,
                     "width": W, "height": H, "fps": float(FPS.fps), "frames": e - s,
                     "out": str(out), "still": str(out_dir / "stills" / f"{item['id']}.png"),
                     "codec": codec, "concurrency": 12})
    return jobs


# ── rendering ───────────────────────────────────────────────────────────────


def render(jobs: List[dict], timeout: float = 7200) -> List[dict]:
    ensure_installed()
    for j in jobs:
        Path(j["out"]).parent.mkdir(parents=True, exist_ok=True)
        Path(j["still"]).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "jobs.json"
        spec.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        proc = subprocess.Popen(["node", str(GRAPHICS_DIR / "render.mjs"), str(spec)],
                                cwd=GRAPHICS_DIR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace")
        results = []
        for line in proc.stdout:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "out" in r:
                results.append(r)
                print(("ok  " if r["ok"] else "ERR ") + Path(r["out"]).name
                      + ("" if r["ok"] else "  " + r.get("error", "")[:400]), flush=True)
        proc.wait(timeout=timeout)
    return results


def checks(plan: dict, jobs: List[dict]) -> Path:
    """Each still composited into its 4K layout over the episode frame it
    lands on, plus one contact sheet of them all."""
    from PIL import Image, ImageDraw
    from caption_engine.media import ffmpeg_bin

    out_dir = Path(plan["out_dir"]) / "checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    items = {i["id"]: i for i in plan["items"]}
    layouts = {k: Image.open(v["png"]).convert("RGBA") for k, v in LAYOUTS.items()}
    thumbs = []
    for j in jobs:
        item = items[j["id"]]
        t = item["start"] + 0.6 * (item["end"] - item["start"])
        frame = out_dir / f"_{j['id']}_frame.png"
        subprocess.run([ffmpeg_bin("ffmpeg"), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", plan["video"],
                        "-frames:v", "1", str(frame)], check=True)
        bg = Image.open(frame).convert("RGBA").resize(SEQ_SIZE)
        g = Image.open(j["still"]).convert("RGBA")
        cx, cy = position(item["layout"])
        bg.alpha_composite(g, (round(cx - g.width / 2), round(cy - g.height / 2)))
        bg.alpha_composite(layouts[item["layout"]])
        small = bg.convert("RGB").resize((1280, 720))
        small.save(out_dir / f"{j['id']}.jpg", quality=85)
        frame.unlink()
        thumbs.append((j["id"], small.resize((640, 360))))
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (640 * cols, 380 * rows), "black")
    d = ImageDraw.Draw(sheet)
    for n, (name, im) in enumerate(thumbs):
        x, y = (n % cols) * 640, (n // cols) * 380
        sheet.paste(im, (x, y + 20))
        d.text((x + 6, y + 4), name, fill="white")
    path = out_dir / "sheet.jpg"
    sheet.save(path, quality=85)
    return path


# ── XML ─────────────────────────────────────────────────────────────────────


def _t(parent, tag, value=None):
    el = ET.SubElement(parent, tag)
    if value is not None:
        el.text = str(value)
    return el


def _rate(parent):
    r = _t(parent, "rate")
    _t(r, "timebase", FPS.timebase)
    _t(r, "ntsc", "TRUE" if FPS.ntsc else "FALSE")
    return r


def _transition(start: int, end: int, alignment: str):
    tr = ET.Element("transitionitem")
    _t(tr, "start", start)
    _t(tr, "end", end)
    _t(tr, "alignment", alignment)
    # Written the way Premiere writes a fade: the cut point sits at the clip's
    # own edge, 0 ticks in for a head fade and the full length for a tail.
    ticks = 0 if alignment == "start-black" else \
        round((end - start) * TICKS_PER_SECOND * float(1 / FPS.fps))
    _t(tr, "cutPointTicks", ticks)
    _rate(tr)
    eff = _t(tr, "effect")
    for k, v in (("name", "Cross Dissolve"), ("effectid", "Cross Dissolve"),
                 ("effectcategory", "Dissolve"), ("effecttype", "transition"),
                 ("mediatype", "video"), ("wipecode", 0), ("wipeaccuracy", 100),
                 ("startratio", 0), ("endratio", 1), ("reverse", "FALSE")):
        _t(eff, k, v)
    return tr


def _file(fid: str, path: str, frames: int, size, audio: bool = False):
    f = ET.Element("file", id=fid)
    _t(f, "name", Path(path).name)
    _t(f, "pathurl", to_pathurl(path))
    _rate(f)
    _t(f, "duration", frames)
    tc = _t(f, "timecode")
    _rate(tc)
    _t(tc, "string", "00;00;00;00")
    _t(tc, "frame", 0)
    _t(tc, "displayformat", "DF")
    m = _t(f, "media")
    v = _t(m, "video")
    sc = _t(v, "samplecharacteristics")
    _rate(sc)
    _t(sc, "width", size[0])
    _t(sc, "height", size[1])
    _t(sc, "anamorphic", "FALSE")
    _t(sc, "pixelaspectratio", "square")
    _t(sc, "fielddominance", "none")
    if audio:
        a = _t(m, "audio")
        _t(a, "channelcount", 2)
        asc = _t(a, "samplecharacteristics")
        _t(asc, "depth", 16)
        _t(asc, "samplerate", 48000)
    return f


def _scale_filter(scale: float):
    filt = ET.Element("filter")
    eff = _t(filt, "effect")
    for k, v in (("name", "Basic Motion"), ("effectid", "basic"), ("effectcategory", "motion"),
                 ("effecttype", "motion"), ("mediatype", "video")):
        _t(eff, k, v)
    p = _t(eff, "parameter")
    for k, v in (("parameterid", "scale"), ("name", "Scale"), ("valuemin", 0),
                 ("valuemax", 1000), ("value", scale)):
        _t(p, k, v)
    return filt


def _bin(parent, name: str):
    b = _t(parent, "bin")
    _t(b, "name", name)
    return _t(b, "children")


def _masterclip(parent, mcid: str, name: str, file_el, frames: int):
    """A project item, in the shape Premiere and FCP7 write them: the clip holds
    one clipitem that carries the file's full definition. Sequence clipitems
    then name it by ``masterclipid`` and reference the file by bare id, so the
    import lands each file once, in the bin it's defined in."""
    clip = ET.SubElement(parent, "clip", id=mcid)
    _t(clip, "masterclipid", mcid)
    _t(clip, "ismasterclip", "TRUE")
    _t(clip, "name", name)
    _t(clip, "duration", frames)
    _rate(clip)
    tr = _t(_t(_t(clip, "media"), "video"), "track")
    ci = ET.SubElement(tr, "clipitem", id=f"{mcid}-item")
    _t(ci, "masterclipid", mcid)
    _t(ci, "name", name)
    _t(ci, "duration", frames)
    _rate(ci)
    ci.append(file_el)
    return clip


# Default bin for a graphic by its layout; an item's own "bin" wins.
DEFAULT_BINS = {"news": "News (V8)", "guest": "Guests (V9)"}
STILL_FRAMES = 150


def write_xml(plan: dict, out_path: Optional[Path] = None) -> Path:
    """One 4K sequence — the render on V1/A1-2 for reference, graphics on
    V8/V9 — inside an organised bin tree: timelines, graphics per segment,
    and assets (the render, the layouts, the source screenshots)."""
    from caption_engine.media import probe
    from PIL import Image

    video = plan["video"]
    info = probe(video)
    total = FPS.to_frames(info["duration"])
    name = plan.get("name", "panels")
    ref_w = (info["width"], info["height"])
    items = sorted(plan["items"], key=lambda i: i["start"])

    root = ET.Element("xmeml", version="5")
    top = _bin(root, name)

    # ── bins first, so every file is defined where it should live ──
    graphics = _bin(top, "02 Graphics")
    group_bins = {}
    for item in items:  # bins in the order segments appear
        label = item.get("bin") or DEFAULT_BINS[item["layout"]]
        if label not in group_bins:
            group_bins[label] = _bin(graphics, label)
        s, e = frames_of(item)
        path = Path(plan["out_dir"]) / f"{item['id']}_{item['layout']}.mp4"
        _masterclip(group_bins[label], f"mc-{item['id']}", path.name,
                    _file(f"file-{item['id']}", str(path), e - s, LAYOUTS[item["layout"]]["size"]), e - s)

    assets = _bin(top, "03 Assets")
    _masterclip(_bin(assets, "Reference render"), "mc-ref", Path(video).name,
                _file("ref-file", video, total, ref_w, audio=True), total)
    layouts = _bin(assets, "Layouts")
    for key, lay in LAYOUTS.items():
        with Image.open(lay["png"]) as im:
            size = im.size
        _masterclip(layouts, f"mc-layout-{key}", lay["png"].name,
                    _file(f"file-layout-{key}", str(lay["png"]), STILL_FRAMES, size), STILL_FRAMES)
    shots_dir = Path(plan.get("shots_dir") or Path(plan["_dir"]) / "shots")
    used = sorted({i["shot"] for i in items if i.get("shot")})
    if used:
        shots = _bin(assets, "Screenshots")
        for sname in used:
            png = shots_dir / f"{sname}.png"
            if not png.exists():
                continue
            with Image.open(png) as im:
                size = im.size
            _masterclip(shots, f"mc-shot-{sname}", png.name,
                        _file(f"file-shot-{sname}", str(png), STILL_FRAMES, size), STILL_FRAMES)

    seq = ET.SubElement(_bin(top, "01 Timelines"), "sequence", id="panels-seq")
    _t(seq, "uuid", str(uuid.uuid5(uuid.NAMESPACE_URL, name)))
    _t(seq, "duration", total)
    _rate(seq)
    _t(seq, "name", name)
    media = _t(seq, "media")
    vid = _t(media, "video")
    fmt = _t(vid, "format")
    sc = _t(fmt, "samplecharacteristics")
    _rate(sc)
    _t(sc, "width", SEQ_SIZE[0])
    _t(sc, "height", SEQ_SIZE[1])
    _t(sc, "anamorphic", "FALSE")
    _t(sc, "pixelaspectratio", "square")
    _t(sc, "fielddominance", "none")

    tracks = {n: _t(vid, "track") for n in range(1, 10)}
    # V1: the render itself, scaled to fill 4K, so the timing can be checked in place.
    ci = _t(tracks[1], "clipitem")
    ci.set("id", "ref-v")
    _t(ci, "masterclipid", "mc-ref")
    _t(ci, "name", Path(video).name)
    _t(ci, "enabled", "TRUE")
    _t(ci, "duration", total)
    _rate(ci)
    for k, v in (("start", 0), ("end", total), ("in", 0), ("out", total)):
        _t(ci, k, v)
    ET.SubElement(ci, "file", id="ref-file")
    st = _t(ci, "sourcetrack")
    _t(st, "mediatype", "video")
    _t(st, "trackindex", 1)
    ci.append(_scale_filter(round(100 * SEQ_SIZE[0] / ref_w[0], 3)))

    # Fades only where a run of graphics begins or ends — that's where the
    # layout switches. Back-to-back panels hard-cut to each other; fading both
    # would dip to the camera underneath for a few frames.
    spans = {}
    for item in items:
        spans.setdefault(item["layout"], []).append(frames_of(item))
    for n, item in enumerate(items, start=1):
        s, e = frames_of(item)
        tr = tracks[LAYOUTS[item["layout"]]["track"]]
        path = Path(plan["out_dir"]) / f"{item['id']}_{item['layout']}.mp4"
        head_joined = any(abs(s - pe) <= 1 for _, pe in spans[item["layout"]])
        tail_joined = any(abs(e - ps) <= 1 for ps, _ in spans[item["layout"]])
        if not head_joined:
            tr.append(_transition(s, s + TRANSITION_FRAMES, "start-black"))
        c = _t(tr, "clipitem")
        c.set("id", f"panel-{item['id']}")
        _t(c, "masterclipid", f"mc-{item['id']}")
        _t(c, "name", path.name)
        _t(c, "enabled", "TRUE")
        _t(c, "duration", e - s)
        _rate(c)
        for k, v in (("start", s), ("end", e), ("in", 0), ("out", e - s)):
            _t(c, k, v)
        ET.SubElement(c, "file", id=f"file-{item['id']}")
        st = _t(c, "sourcetrack")
        _t(st, "mediatype", "video")
        _t(st, "trackindex", 1)
        if not tail_joined:
            tr.append(_transition(e - TRANSITION_FRAMES, e, "end-black"))
    for tr in tracks.values():
        _t(tr, "enabled", "TRUE")
        _t(tr, "locked", "FALSE")

    aud = _t(media, "audio")
    for ch in (1, 2):
        at = _t(aud, "track")
        a = _t(at, "clipitem")
        a.set("id", f"ref-a{ch}")
        _t(a, "masterclipid", "mc-ref")
        _t(a, "name", Path(video).name)
        _t(a, "enabled", "TRUE")
        _t(a, "duration", total)
        _rate(a)
        for k, v in (("start", 0), ("end", total), ("in", 0), ("out", total)):
            _t(a, k, v)
        ET.SubElement(a, "file", id="ref-file")
        st = _t(a, "sourcetrack")
        _t(st, "mediatype", "audio")
        _t(st, "trackindex", ch)
        _t(at, "enabled", "TRUE")
        _t(at, "locked", "FALSE")

    # One marker per graphic, so the layout switches are easy to find.
    for item in items:
        s, e = frames_of(item)
        mk = _t(seq, "marker")
        _t(mk, "comment", item.get("note", ""))
        _t(mk, "name", f"{item['id']} · {item['layout'].upper()} · {item['template']}")
        _t(mk, "in", s)
        _t(mk, "out", -1)

    ET.indent(root, space="\t")
    out = Path(out_path or Path(plan["out_dir"]) / f"{name}.xml")
    out.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
                   + ET.tostring(root, encoding="unicode"), encoding="utf-8")
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m clipper.panels")
    ap.add_argument("cmd", choices=["render", "stills", "xml", "checks"])
    ap.add_argument("plan", nargs="+", help="one or more plan files; items are merged")
    ap.add_argument("--only", default=None, help="comma-separated item ids")
    ap.add_argument("--checks", action="store_true", help="after render, composite check images")
    a = ap.parse_args()
    plan = load(a.plan[0])
    for extra in a.plan[1:]:
        plan["items"] += load(extra)["items"]
    only = a.only.split(",") if a.only else None
    if a.cmd == "xml":
        print(write_xml(plan))
        return
    jobs = build_jobs(plan, only)
    if a.cmd == "render":
        render(jobs)
    if a.cmd == "stills":
        # Preview pass: one frame per graphic (late, so every mark has drawn).
        render([{**j, "stillOnly": True, "stillAt": 0.9, "out": j["still"]} for j in jobs])
    if a.cmd in ("checks", "stills") or a.checks:
        print(checks(plan, jobs))


if __name__ == "__main__":
    main()
