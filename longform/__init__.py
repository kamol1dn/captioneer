"""Long-form episode tooling: graphics for the layout panes, and text layers.

A show's long-form config (pane geometry, tracks, text-layer limits) is its
``shows/<id>/longform.json``, in the client tier (see caption_engine.shows).
The plans that drive ``clipper.panels`` and ``clipper.headlines`` live with the
episode, next to its Premiere project, never in the engine repo.
"""
from caption_engine import shows as shows_root


def show_config(show: str) -> dict:
    d = shows_root.read_json(show, "longform.json")
    if d is None:
        raise FileNotFoundError(f"no long-form config for show {show!r}: "
                                f"expected {shows_root.show_dir(show) / 'longform.json'}")
    return d
