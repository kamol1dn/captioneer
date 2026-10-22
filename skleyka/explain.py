"""Type 1, the explaining lower third, as native-feeling stills.

The editor's own graphic is three Premiere layers: a soft dark scrim, a bold
title, a regular explanation line, fading in and out together. Skleyka does
the same with three PNGs (one scrim, reused; the two text lines rendered
here with the show's Helvetica), placed as stills on lanes "SKL scrim",
"SKL title" and "SKL detail" in the editor's staircase (title 4 frames
after the scrim, line 8; ending 6 and 4 frames before it), a 4-frame Cross
Dissolve on every edge, and the editor's whoosh 0.1 s before at -15 dB. Small files, no renders, each
layer still movable in Premiere.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import overlays, timeline

FONTS = Path(__file__).resolve().parents[1] / "graphics" / "public" / "fonts"
WHOOSH = r"C:\Users\User\Documents\editing assets\SOUNDS\Whoosh 1  Slow, Thick.wav"
WHOOSH_LEAD = 0.1
WHOOSH_LEN = 5.07
WHOOSH_GAIN_DB = -15
# Measured on the editor's graphic (behzod tahlil 00:00:44:14), in frame fractions.
LEFT = 0.124
TITLE_BASE = 0.8395   # baseline of the title (measured against the editor's)
DETAIL_BASE = 0.8985
TEXT_VERSION = 2      # bump when the look changes, so cached PNGs are redone
TITLE_PX = 172        # at 2160 high
DETAIL_PX = 100
FADE_FRAMES = 4


def uz(s: str) -> str:
    """Uzbek apostrophes: oʻ/gʻ take the turned comma, a glottal stop between
    letters the modifier apostrophe (same rule as the Gashtak theme, shows/gashtak/graphics/theme.tsx)."""
    import regex
    s = regex.sub(r"([OoGg])['‘’`ʻʼ]", r"\1ʻ", s)
    return regex.sub(r"(\p{L})['’`ʼ](?=\p{L})", r"\1ʼ", s)


def assets_dir(project_path: str) -> Path:
    d = timeline.workdir(project_path) / "assets"
    d.mkdir(exist_ok=True)
    return d


def scrim_png(project_path: str, width: int = 3840, height: int = 2160) -> Path:
    out = assets_dir(project_path) / "scrim_bottom_left.png"
    if out.exists():
        return out
    import numpy as np
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy, rx, ry = 0.15 * width, 0.98 * height, 0.62 * width, 0.46 * height
    d = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
    alpha = np.clip(1 - (d - 0.15) / 0.85, 0, 1) ** 1.6 * 0.84
    img = np.zeros((height, width, 4), np.uint8)
    img[..., 3] = (alpha * 255).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(out, optimize=True)
    return out


def text_png(project_path: str, text: str, kind: str, width: int = 3840, height: int = 2160) -> Path:
    """One line of white Helvetica at the lower third's place, full-frame alpha."""
    text = uz(text)
    key = hashlib.sha1(f"v{TEXT_VERSION}|{kind}|{text}|{width}x{height}".encode("utf-8")).hexdigest()[:10]
    safe = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in text)[:24]
    out = assets_dir(project_path) / f"{kind}_{safe}_{key}.png"
    if out.exists():
        return out
    s = height / 2160
    font = ImageFont.truetype(str(FONTS / ("Helvetica-Bold.ttf" if kind == "title" else "Helvetica.ttf")),
                              round((TITLE_PX if kind == "title" else DETAIL_PX) * s))
    base = (TITLE_BASE if kind == "title" else DETAIL_BASE) * height
    # Plain white type, no shadow or outline: the scrim does the legibility.
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((LEFT * width, base), text, font=font, fill=(255, 255, 255, 255), anchor="ls")
    img.save(out, optimize=True)
    return out


def place_explain(title: str, detail: str | None, at: float, seconds: float = 7.0,
                  whoosh: bool = True, sequence: str | None = None) -> dict:
    """The whole lower third at ``at``: scrim, title, line, whoosh."""
    ctx = overlays._context(sequence)
    fps = overlays.TICKS / int(ctx["frame"])
    end = at + seconds
    placed = []
    label = title[:20]
    # The editor's staircase, read off their graphic (behzod tahlil 43.6 s):
    # scrim first; title in 4 frames later, out 6 frames earlier; line in 8
    # frames later, out 4 frames earlier; 4-frame dissolves on every edge.
    fr = 1.0 / fps
    scrim = overlays.place(str(scrim_png(ctx["project"])), at, end, kind="video", lane="scrim",
                           label=label, sequence=ctx["id"], animate="dissolve")
    placed.append(scrim)
    t_png = text_png(ctx["project"], title, "title")
    placed.append(overlays.place(str(t_png), at + 4 * fr, end - 6 * fr, kind="video", lane="title",
                                 label=label, sequence=ctx["id"], animate="dissolve"))
    if detail:
        d_png = text_png(ctx["project"], detail, "detail")
        placed.append(overlays.place(str(d_png), at + 8 * fr, end - 4 * fr, kind="video", lane="detail",
                                     label=label, sequence=ctx["id"], animate="dissolve"))
    if whoosh and Path(WHOOSH).exists():
        # As the editor places it: 0.1 s early, the first 5 s of the file, -15 dB.
        placed.append(overlays.place(WHOOSH, max(0.0, at - WHOOSH_LEAD), at - WHOOSH_LEAD + WHOOSH_LEN, kind="audio",
                                     lane="whoosh", label=label, style={"gain_db": WHOOSH_GAIN_DB}, sequence=ctx["id"]))
    return {"ids": [p["id"] for p in placed], "lanes": [p["lane"] for p in placed],
            "start": at, "end": end, "title": title, "detail": detail}
