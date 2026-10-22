"""A placement check without Premiere: the graphic's still over the sample
frame of the cut, at the spot free_space proposed. Cheap enough to try a
few spots and sizes before placing; a real grab_frame confirms the final one."""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

from . import timeline


def composite(frame_image: str, still: str, box: dict, out: Path, faces: list[dict] | None = None) -> str:
    base = Image.open(frame_image).convert("RGBA")
    W, H = base.size
    ov = Image.open(still).convert("RGBA")
    ow, oh = max(1, round(box["w"] * W)), max(1, round(box["h"] * H))
    ov = ov.resize((ow, oh), Image.LANCZOS)
    base.alpha_composite(ov, (round(box["x"] * W), round(box["y"] * H)))
    if faces:
        d = ImageDraw.Draw(base)
        for f in faces:
            d.rectangle([f["x"] * W, f["y"] * H, (f["x"] + f["w"]) * W, (f["y"] + f["h"]) * H], outline=(255, 255, 255, 110), width=1)
    base.convert("RGB").save(out, quality=88)
    return str(out)


def preview(project_path: str, sample: dict, still: str, box: dict, at: float) -> str:
    d = timeline.workdir(project_path) / "samples"
    out = d / f"preview_{int(round(at * 1000)):09d}_{time.strftime('%H%M%S')}.jpg"
    return composite(sample["image"], still, box, out, sample.get("faces"))
