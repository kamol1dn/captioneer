"""Where the client tier lives: one folder per show, outside the engine's git.

The engine is the public part. Everything that makes a reel look like one
client's show (its caption presets, graphics family, fonts, whooshes, outro,
long-form layouts and the written rules an editor follows) lives in
``shows/<id>/``, which the engine repo ignores and each show versions in its own
private repo. Per-episode files sit next to that episode's Premiere project, not
here.

``CAPTIONEER_SHOWS`` points the engine at a shows folder somewhere else; by
default it is ``shows/`` at the repo root. A missing folder is not an error: the
engine with no shows still cuts and captions, it just dresses nothing.

Layout of one show (every file optional)::

    shows/<id>/
      show.json       reel dressing, read by clipper.show
      captions.json   {"group": "English", "presets": {name: CaptionStyle dict}}
      templates.json  {"templates": {name: spec}}: its graphics, see clipper.graphics
      graphics/       Remotion components, synced into graphics/src/<id>/
      fonts/          synced into graphics/public/fonts/
      longform.json   long-form pane layouts, read by longform.show_config
      RULES.md        how this show is edited; the skills read it

``shows/_shared/`` holds what several shows use (a licensed face both brands
are set in); its ``fonts/`` sync like a show's.
"""
import json
import os
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = "_shared"


def root() -> Path:
    env = os.environ.get("CAPTIONEER_SHOWS")
    return Path(env) if env else REPO_ROOT / "shows"


def show_dir(show_id: str) -> Path:
    return root() / show_id


def known() -> List[str]:
    """Show ids: folders with a show.json, ``_shared`` and dot-folders aside."""
    r = root()
    if not r.is_dir():
        return []
    return sorted(p.name for p in r.iterdir()
                  if p.is_dir() and not p.name.startswith(("_", "."))
                  and (p / "show.json").is_file())


def read_json(show_id: str, name: str) -> Optional[dict]:
    """``shows/<id>/<name>`` parsed, or None when the show has no such file."""
    path = show_dir(show_id) / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def each_json(name: str):
    """(show_id, parsed) for every show that has ``name``."""
    for sid in known():
        d = read_json(sid, name)
        if d is not None:
            yield sid, d
