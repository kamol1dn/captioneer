"""Locating font files for caption rendering.

Fonts live under the project's `assets-fonts/` directory; these helpers find a
bundled bold text font and the bundled color-emoji font.
"""
import os
from collections import OrderedDict

# Font file extensions we offer in the picker.
_FONT_EXTS = (".ttf", ".otf", ".ttc")


def _project_root() -> str:
    # caption_engine/style/fonts.py -> project root is three levels up.
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def default_emoji_font() -> str:
    p = os.path.join(
        _project_root(),
        "assets-fonts", "ios-emojis", "AppleColorEmoji-Windows.ttf",
    )
    return p if os.path.exists(p) else ""


def list_available_fonts() -> "OrderedDict[str, str]":
    """Return {display_name: path} for every bundled text font, sorted by name.

    Scans `assets-fonts/` recursively for .ttf/.otf/.ttc files, excluding the
    color-emoji font (it isn't a text face). Display names are the file stems;
    on a stem collision the parent folder is appended to keep keys unique.
    """
    root = os.path.join(_project_root(), "assets-fonts")
    found: list = []  # (label, path)
    seen_labels: dict = {}
    for dirpath, _dirs, files in os.walk(root):
        if "ios-emojis" in dirpath.replace("\\", "/").split("/"):
            continue  # skip the emoji font directory
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
        # Project-bundled font (highest priority)
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
