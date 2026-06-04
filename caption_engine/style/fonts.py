"""Locating font files for caption rendering.

Fonts live under the project's `assets-fonts/` directory; these helpers find a
bundled bold text font and the bundled color-emoji font.
"""
import os


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
