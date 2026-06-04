"""The CaptionStyle dataclass: all style/layout settings for rendering."""
from dataclasses import dataclass, field
from typing import Tuple, Literal

from .fonts import find_system_font, default_emoji_font

RGBA = Tuple[int, int, int, int]
RGB = Tuple[int, int, int]


@dataclass
class CaptionStyle:
    """All style/layout settings for caption rendering.

    Designed so it can be serialized to JSON for presets, GUI bindings, etc.
    """

    # ── Canvas ──────────────────────────────────────────────────────────────
    width: int = 1440
    height: int = 0             # 0 = auto-size to caption strip height
    fps: int = 30

    # ── Typography ──────────────────────────────────────────────────────────
    font_path: str = field(default_factory=find_system_font)
    emoji_font_path: str = field(default_factory=default_emoji_font)
    font_size: int = 96
    line_spacing: float = 1.15  # multiplier of font height

    # ── Layout ──────────────────────────────────────────────────────────────
    max_chars_per_line: int = 16
    max_lines_visible: int = 1
    # vertical position as fraction of canvas height (0 = top, 1 = bottom)
    vertical_anchor: float = 0.5
    horizontal_padding: int = 60

    # ── Colors ──────────────────────────────────────────────────────────────
    text_color: RGBA = (255, 255, 255, 255)
    highlight_color: RGBA = (255, 220, 0, 255)        # active word
    text_stroke_color: RGBA = (0, 0, 0, 0)
    text_stroke_width: int = 6

    # ── Background box behind text (optional) ───────────────────────────────
    bg_enabled: bool = True
    bg_color: RGBA = (0, 0, 0, 230)
    bg_padding: int = 24
    bg_radius: int = 18

    # ── Highlight animation ─────────────────────────────────────────────────
    # "none"  : just color change
    # "scale" : pop/scale the active word
    # "box"   : draw a colored box behind the active word
    highlight_mode: Literal["none", "scale", "box"] = "none"
    highlight_scale: float = 1.15                     # only used for "scale"
    highlight_box_color: RGBA = (255, 80, 80, 255)    # only used for "box"
    highlight_box_padding: int = 8

    # ── Word entry animation (subtle pop) ──────────────────────────────────
    entry_anim: Literal["none", "pop"] = "none"
    entry_anim_duration: float = 0.08   # seconds

    # ── Phrase transition ───────────────────────────────────────────────────
    # "none" : phrase shows/hides instantly (bridged by phrase_hold)
    # "fade" : fade the phrase in over `transition_frames`, and out over the
    #          same, sequentially — the old phrase fully fades out before the
    #          next fades in (not a cross-dissolve).
    transition: Literal["none", "fade"] = "none"
    transition_frames: int = 0          # frames for each of fade-in / fade-out

    # ── Word grouping behaviour ─────────────────────────────────────────────
    # If gap between words > this many seconds, force a new "phrase"/segment
    phrase_gap_threshold: float = 0.7
    # After a phrase's last word ends, keep showing its final frame for this many
    # seconds (clamped so it never bleeds into the next phrase). Bridges the gap
    # between phrases so the caption doesn't blink off and flicker. 0 = disabled.
    phrase_hold: float = 1.0

    def __post_init__(self):
        if self.height == 0:
            line_h = int(self.font_size * self.line_spacing)
            self.height = line_h * self.max_lines_visible + self.bg_padding * 2 + 60

    def to_dict(self) -> dict:
        return {k: list(v) if isinstance(v, tuple) else v
                for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "CaptionStyle":
        # convert lists back to tuples for color fields
        for key in ("text_color", "highlight_color", "text_stroke_color",
                    "bg_color", "highlight_box_color"):
            if key in d and isinstance(d[key], list):
                d[key] = tuple(d[key])
        return cls(**d)
