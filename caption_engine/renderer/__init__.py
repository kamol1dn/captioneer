"""Frame renderer: Phrases + CaptionStyle -> transparent ProRes 4444 .mov.

Submodules:
* `fonts`   — font loading/caching
* `text`    — emoji-aware text measurement and drawing
* `phrase`  — active-phrase lookup and drawing one phrase frame
* `encoder` — the ffmpeg pipeline (the public `render_to_mov`)
"""
from .encoder import render_to_mov
from .preview import render_frame, render_preview_overlay

__all__ = ["render_to_mov", "render_frame", "render_preview_overlay"]
