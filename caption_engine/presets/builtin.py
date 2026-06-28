"""Pre-made style presets. Easy starting points for users."""
from ..style import CaptionStyle


def reels_classic() -> CaptionStyle:
    """White text, black stroke, yellow highlight - the Reels/TikTok standard."""
    return CaptionStyle(
        font_size=90,
        max_chars_per_line=16,
        text_color=(255, 255, 255, 255),
        highlight_color=(255, 220, 0, 255),
        text_stroke_color=(0, 0, 0, 255),
        text_stroke_width=6,
        highlight_mode="scale",
        highlight_scale=1.18,
    )


def bold_yellow_box() -> CaptionStyle:
    """White text with yellow box behind the active word. Very modern."""
    return CaptionStyle(
        font_size=85,
        max_chars_per_line=18,
        text_color=(255, 255, 255, 255),
        text_stroke_color=(0, 0, 0, 255),
        text_stroke_width=5,
        highlight_mode="box",
        highlight_box_color=(255, 200, 0, 255),
        highlight_color=(0, 0, 0, 255),   # active word turns black on yellow
        highlight_box_padding=10,
    )


def minimal_white() -> CaptionStyle:
    """Clean white text, no stroke, no highlight box. Subtle scale on active word."""
    return CaptionStyle(
        font_size=80,
        max_chars_per_line=20,
        text_color=(230, 230, 230, 255),
        highlight_color=(255, 255, 255, 255),
        text_stroke_width=0,
        text_stroke_color=(0, 0, 0, 0),
        bg_enabled=True,
        bg_color=(0, 0, 0, 140),
        highlight_mode="scale",
        highlight_scale=1.10,
    )


def punchy_green() -> CaptionStyle:
    """High-energy green highlight, larger scale pop."""
    return CaptionStyle(
        font_size=95,
        max_chars_per_line=14,
        text_color=(255, 255, 255, 255),
        highlight_color=(0, 255, 130, 255),
        text_stroke_color=(0, 0, 0, 255),
        text_stroke_width=7,
        highlight_mode="scale",
        highlight_scale=1.22,
    )


def gashtak_main() -> CaptionStyle:
    """Uzbek base style: small clean text, no background, no word highlight,
    quick 2-frame fade between phrases (not a cross-dissolve).

    Font is ~half the English presets (48 vs ~90), same family (the bundled
    Montserrat-Bold default). A light stroke keeps it legible without a box.
    """
    return CaptionStyle(
        font_size=64,                       # any size now; emoji scales independently
        max_chars_per_line=25,              # smaller font fits more per line
        text_color=(255, 255, 255, 255),
        text_stroke_color=(0, 0, 0, 255),
        text_stroke_width=0,
        bg_enabled=False,                   # no background
        highlight_mode="none",              # no word highlighting
        transition="fade",                  # 2-frame fade out, then 2-frame fade in
        transition_frames=2,
        phrase_hold=0.5,                    # snappier than the 1.0s English default
        bg_offset_y=15,                     # slightly higher than the English default
    )


def gashtak_2() -> CaptionStyle:
    """Like gashtak_main but with a subtle background box and word highlighting."""
    return CaptionStyle(
        font_size=64,                       # any size now; emoji scales independently
        max_chars_per_line=28,
        text_color=(255, 255, 255, 255),
        text_stroke_color=(0, 0, 0, 255),
        text_stroke_width=0,
        bg_enabled=True,                    # subtle background
        bg_color=(0, 0, 0, 140),
        highlight_mode="none",             # word highlighting
        highlight_scale=1.12,
        highlight_color=(255, 220, 0, 255),
        transition="fade",
        transition_frames=2,
        phrase_hold=0.5,
        bg_offset_y=-8,  
        letter_spacing=-1,                   # tight tracking is common in Uzbek captions
    )


def otg_cyan() -> CaptionStyle:
    """On-the-go cyan preset, optimized for mobile viewing."""
    return CaptionStyle(
        font_size=70,
        max_chars_per_line=24,
        text_color=(255, 255, 255, 255),
        text_stroke_color=(0, 0, 0, 0),
        text_stroke_width=0,
        highlight_mode="none",
        highlight_box_color=(0, 255, 255, 255),
        highlight_color=(25, 224, 214, 255),   # active word turns black on cyan
        highlight_box_padding=10,
    )
