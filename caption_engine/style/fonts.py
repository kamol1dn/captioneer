"""Locating font files for caption rendering.

The engine bundles free fonts under `assets-fonts/`. Licensed faces a client's
brand is set in live in the client tier instead (`shows/_shared/fonts/` and
`shows/<id>/fonts/`, see caption_engine.shows), and are offered alongside.
"""
import os
from collections import OrderedDict

# Font file extensions we offer in the picker.
_FONT_EXTS = (".ttf", ".otf", ".ttc")


def _project_root() -> str:
    # caption_engine/style/fonts.py -> project root is three levels up.
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _font_roots() -> list:
    """The engine's bundled fonts, then the shows' (shared first)."""
    from .. import shows
    roots = [os.path.join(_project_root(), "assets-fonts"),
             str(shows.root() / shows.SHARED / "fonts")]
    roots += [str(shows.show_dir(sid) / "fonts") for sid in shows.known()]
    return [r for r in roots if os.path.isdir(r)]


def default_emoji_font() -> str:
    """The color-emoji font, from any font root's `ios-emojis/` (not bundled:
    Apple's face is not ours to redistribute, so it lives with the shows)."""
    for root in _font_roots():
        p = os.path.join(root, "ios-emojis", "AppleColorEmoji-Windows.ttf")
        if os.path.exists(p):
            return p
    return ""


def list_available_fonts() -> "OrderedDict[str, str]":
    """Return {display_name: path} for every bundled text font, sorted by name.

    Scans every font root recursively for .ttf/.otf/.ttc files, excluding the
    color-emoji font (it isn't a text face) and the `graphics/` sets the
    Remotion renderer uses. Display names are the file stems;
    on a stem collision the parent folder is appended to keep keys unique.
    """
    found: list = []  # (label, path)
    seen_labels: dict = {}
    for root in _font_roots():
        for dirpath, _dirs, files in os.walk(root):
            parts = dirpath.replace("\\", "/").split("/")
            if "ios-emojis" in parts or "graphics" in parts:
                continue
            for name in files:
                if not name.lower().endswith(_FONT_EXTS):
                    continue
                path = os.path.join(dirpath, name)
                label = os.path.splitext(name)[0]
                if label in seen_labels:
                    label = f"{label} ({os.path.basename(dirpath)})"
                seen_labels[label] = path
                found.append((label, path))
    found.sort(key=lambda lp: lp[0].lower())
    return OrderedDict(found)


def find_system_font() -> str:
    """Return a path to a usable bold font. Tries common locations on all platforms."""
    root = _project_root()
    _win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates = [
        # The engine's bundled face. A show that wants its own brand font names
        # it in its captions.json presets.
        os.path.join(root, "assets-fonts", "monsterrat", "static", "Montserrat-Bold.ttf"),
        # Windows
        # os.path.join(_win, "arialbd.ttf"),
        # os.path.join(_win, "calibrib.ttf"),
        # os.path.join(_win, "trebucbd.ttf"),
        # os.path.join(_win, "verdanab.ttf"),
        # # macOS
        # "/Library/Fonts/Arial Bold.ttf",
        # "/System/Library/Fonts/Helvetica.ttc",
        # # Linux
        # "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
        # "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        # "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""
