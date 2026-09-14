"""Long-form episode tooling: graphics for the layout panes, and text layers.

One folder per show (``longform/otg``) holds its ``show.json`` — pane
geometry, tracks, text-layer limits — and one subfolder per episode with the
plans that drive ``clipper.panels`` and ``clipper.headlines``. Media stays in
the episode's own folder on disk; only the plans live here.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def show_config(show: str) -> dict:
    import json
    return json.loads((ROOT / show / "show.json").read_text(encoding="utf-8"))
