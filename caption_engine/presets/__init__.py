"""Named style presets, resolved through the user's preferences store.

Presets used to be hardcoded factory functions. They now live in the root
``preferences.json`` (seeded from :mod:`caption_engine.presets.builtin` on first
run), so the GUI can create and edit them. ``builtin.py`` is kept as the seed /
"reset to defaults" source of truth.

``get(name)`` and the ``PRESETS`` / ``PRESET_GROUPS`` names are preserved so the
CLI and any existing importers keep working.
"""
from ..style import CaptionStyle
from .builtin import (
    reels_classic, bold_yellow_box, minimal_white, punchy_green, otg_cyan,
    gashtak_main, gashtak_2,
)

# The built-in seed set, still importable for reference/reset. The live library
# (including user-created presets) comes from the preferences store below.
PRESETS = {
    "otg_cyan": otg_cyan,
    "reels_classic": reels_classic,
    "bold_yellow_box": bold_yellow_box,
    "minimal_white": minimal_white,
    "punchy_green": punchy_green,
    "gashtak_main": gashtak_main,
    "gashtak_2": gashtak_2,
}

# Default grouping used to seed preferences.json. The live grouping (which the
# GUI can extend) is read from the store via ``groups()``.
PRESET_GROUPS = {
    "English": ["otg_cyan", "reels_classic", "bold_yellow_box",
                "minimal_white", "punchy_green"],
    "Uzbek": ["gashtak_2", "gashtak_main"],
}


def get(name: str) -> CaptionStyle:
    """Instantiate a preset by name from the preferences store."""
    from .. import preferences
    return preferences.get_preset(name)


def names() -> list:
    """All preset names currently in the library (for CLI choices, etc.)."""
    from .. import preferences
    return list(preferences.list_presets().keys())


def groups() -> dict:
    """{language: [preset_name, ...]} from the store; first name is the
    default."""
    from .. import preferences
    return preferences.list_groups()


__all__ = [
    "PRESETS", "PRESET_GROUPS", "get", "names", "groups",
    "reels_classic", "bold_yellow_box", "minimal_white", "punchy_green", "otg_cyan",
    "gashtak_main", "gashtak_2",
]
