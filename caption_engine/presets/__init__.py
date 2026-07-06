"""Named style presets and the registry used to look them up."""
from ..style import CaptionStyle
from .builtin import (
    reels_classic, bold_yellow_box, minimal_white, punchy_green, otg_cyan,
    gashtak_main, gashtak_2,
)

PRESETS = {
    "otg_cyan": otg_cyan,
    "reels_classic": reels_classic,
    "bold_yellow_box": bold_yellow_box,
    "minimal_white": minimal_white,
    "punchy_green": punchy_green,
    "gashtak_main": gashtak_main,
    "gashtak_2": gashtak_2,
}

# Presets grouped by the language they're intended for. The first entry in each
# list is that language's default. The GUI uses this to repopulate the preset
# dropdown when the language changes.
PRESET_GROUPS = {
    "English": ["otg_cyan", "reels_classic", "bold_yellow_box",
                "minimal_white", "punchy_green"],
    "Uzbek": ["gashtak_2", "gashtak_main"],
}


def get(name: str) -> CaptionStyle:
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset '{name}'. Available: {list(PRESETS.keys())}"
        )
    return PRESETS[name]()


__all__ = [
    "PRESETS", "PRESET_GROUPS", "get",
    "reels_classic", "bold_yellow_box", "minimal_white", "punchy_green", "otg_cyan",
    "gashtak_main", "gashtak_2",
]
