"""Props for the Website template (a web page full screen in a short).

    python -m clipper.webcard <shot.png> --seconds 7 --mark 0:marker@0.25
        [--mark 1:underline@0.55] [--caption "..."] [--source "CNBC · 10 SEP"]
        [--url ...] [--from-top] [--zoom 1.6]

The screenshot comes from ``python -m longform.shoot`` — a page capture plus a
``<shot>.json`` with the line boxes of each ``--mark`` phrase. Shoot it with
``--mobile``: the phone layout's single column fills the window at a size that
reads, where a desktop page shrunk into 9:16 does not. This works out
what the vertical window shows of it: the text column the marks sit in, a
scroll that has each phrase in view before it draws, and a push-in strong
enough that the marked line reads on a phone. The capture is cropped to what
the window will ever show (Chrome composites the whole image every frame).

``--mark PHRASE:STYLE@AT`` — PHRASE is the index (or exact text) of a phrase in
the shot's json, STYLE marker|underline|box, AT the fraction of the graphic's
duration at which it starts drawing. The first mark is where the camera goes.

Prints the props as JSON, ready for render_graphics with template "Website".
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from .panels import _precrop, _scroll_path

# Mirrors WEB and SAFE in graphics/src (vertical.tsx, theme.tsx), in 1080-wide
# design units on a 9:16 frame. The window keeps out of the outer ~9% each
# side, which tall phones crop off.
_FRAME_H = 1920
_WIN_W = 1080 - 2 * 100
_WIN_H = _FRAME_H * (0.635 - 0.215)
_BAR = 64
_CAP = 190 + 26
# A marked line this tall (design units) reads on a phone: ~50 px at 1440x2560.
_READ_H = 38


def website_props(shot: Union[str, Path],
                  marks: Sequence[Tuple[Union[int, str], str, float]],
                  seconds: float,
                  caption: Optional[str] = None,
                  source: Optional[str] = None,
                  url: Optional[str] = None,
                  from_top: bool = False,
                  zoom: Optional[float] = None) -> dict:
    shot = Path(shot)
    meta = json.loads(shot.with_suffix(".json").read_text(encoding="utf-8"))
    W0, H0 = meta["imgW"], meta["imgH"]

    rects, blocks, first = [], [], []
    for n, (phrase, style, at) in enumerate(marks):
        ph = meta["marks"][phrase] if isinstance(phrase, int) else \
            next(x for x in meta["marks"] if x["phrase"] == phrase)
        if not ph["rects"]:
            raise ValueError(f"{shot.name}: phrase not on the page: {ph['phrase']!r}")
        if ph.get("block"):
            blocks.append(ph["block"])
        for j, r in enumerate(ph["rects"]):
            m = {**r, "style": style, "at": round(at + j * 0.45 / seconds, 4)}
            rects.append(m)
            if n == 0:
                first.append(m)

    # The column: whole paragraph width when the shot recorded it, else the
    # marks with a margin, else (no marks: a hero headline, where the caption
    # does the work) the page's full width. Never narrower than 40% of the page.
    spans = [(b["x"], b["x"] + b["w"]) for b in blocks] or \
        [(m["x"], m["x"] + m["w"]) for m in rects] or [(0.025, 0.975)]
    left, right = min(a for a, _ in spans), max(b for _, b in spans)
    pad = 0.025
    x0, x1 = max(0.0, left - pad), min(1.0, right + pad)
    if x1 - x0 < 0.4:
        mid = (x0 + x1) / 2
        x0, x1 = max(0.0, mid - 0.2), min(1.0, mid + 0.2)
    k = _WIN_W / ((x1 - x0) * W0)            # design units per image px
    view_h = _WIN_H - _BAR - (_CAP if caption else 0)
    view = view_h / (H0 * k)                  # visible fraction of the image
    lim = max(0.0, 1 - (_WIN_H - _BAR) / (H0 * k))
    clamp = lambda v: round(min(lim, max(0.0, v)), 4)

    props = {"image": str(shot), "imgW": W0, "imgH": H0,
             "x0": round(x0, 4), "x1": round(x1, 4), "marks": rects}
    if rects:
        props["path"] = _scroll_path(rects, view, clamp, seconds, from_top)
        fx0 = min(m["x"] for m in first)
        fx1 = max(m["x"] + m["w"] for m in first)
        fy0 = min(m["y"] for m in first)
        fy1 = max(m["y"] + m["h"] for m in first)
        props["focus"] = {"x": fx0, "y": fy0, "w": fx1 - fx0, "h": fy1 - fy0, "at": first[0]["at"]}
        if zoom is None:
            line_h = min(m["h"] for m in first) * H0 * k
            # Never past the width the text column fits in: a push-in that
            # clips letters off both edges of every line reads as broken, and
            # a phone capture already reads without one. Up to that limit,
            # enough to make the marked line phone-sized, and a little motion
            # (1.08) even when it already is.
            fit_w = 0.96 * (x1 - x0) / (right - left)
            fit_h = 0.8 * view_h / ((fy1 - fy0) * H0 * k)
            zoom = max(1.0, min(2.2, fit_w, fit_h, max(1.08, _READ_H / max(line_h, 1e-6))))
    props["zoom"] = round(zoom or 1.0, 3)

    # Crop to what the window ever shows, and remap marks, focus and scroll.
    tag = hashlib.sha1(json.dumps([str(shot), props["x0"], props["x1"], props.get("path")]).encode()).hexdigest()[:8]
    full_view = (_WIN_H - _BAR) / (H0 * k)
    focus = props.pop("focus", None)
    if focus:  # ride along with the marks so the crop remaps it the same way
        props["marks"] = props["marks"] + [focus]
    props = _precrop(props, {"id": f"v_{shot.stem}_{tag}"}, full_view, shot.parent)
    if focus:
        *props["marks"], props["focus"] = props["marks"]
    if caption:
        props["caption"] = caption
    if source:
        props["source"] = source
    u = url or meta.get("url", "")
    props["url"] = u.split("://", 1)[-1].removeprefix("www.")
    return props


def _parse_mark(s: str) -> Tuple[Union[int, str], str, float]:
    phrase, rest = s.rsplit(":", 1)
    style, at = rest.split("@")
    return (int(phrase) if phrase.isdigit() else phrase), style, float(at)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m clipper.webcard", description=__doc__.split("\n")[0])
    ap.add_argument("shot")
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--mark", action="append", default=[])
    ap.add_argument("--caption")
    ap.add_argument("--source")
    ap.add_argument("--url")
    ap.add_argument("--from-top", action="store_true")
    ap.add_argument("--zoom", type=float)
    a = ap.parse_args(argv)
    props = website_props(a.shot, [_parse_mark(m) for m in a.mark], a.seconds, a.caption,
                          a.source, a.url, a.from_top, a.zoom)
    json.dump(props, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
