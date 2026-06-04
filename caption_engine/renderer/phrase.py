"""Finding the active phrase at a given time and drawing one phrase frame."""
import math
from typing import List, Optional
from PIL import Image, ImageDraw

from ..style import CaptionStyle
from ..layout import Phrase
from .fonts import get_font, load_emoji_font, EmojiFont
from .text import measure_word, line_width, draw_text_with_stroke, draw_scaled_word


def _window_end(phrases: List[Phrase], idx: int, hold: float) -> float:
    """End of phrase `idx`'s visible window: its last word plus `hold`, clamped
    to the next phrase's start so two phrases never overlap."""
    end = phrases[idx].end + hold
    if idx + 1 < len(phrases):
        end = min(end, phrases[idx + 1].start)
    return end


def find_active_phrase(
    phrases: List[Phrase], t: float, hold: float = 0.0
) -> Optional[int]:
    """Find phrase active at time t. Returns None if in a gap.

    Each phrase stays active for `hold` seconds past its last word so its final
    frame is held across the gap before the next phrase (instead of blinking
    off).
    """
    for i, p in enumerate(phrases):
        if p.start <= t <= _window_end(phrases, i, hold):
            return i
    return None


def transition_opacity(
    phrases: List[Phrase], idx: int, t: float, style: CaptionStyle
) -> float:
    """Opacity (0-1) for phrase `idx` at time t under the style's transition.

    For "fade", opacity ramps 0→1 over the first `transition_frames` of the
    phrase and 1→0 over the last `transition_frames` of its window. Because the
    window never overlaps the next phrase's start, the fade-out always finishes
    before the next phrase's fade-in begins — i.e. sequential, not a dissolve.
    """
    if style.transition != "fade" or style.transition_frames <= 0:
        return 1.0
    fade = style.transition_frames / style.fps
    p = phrases[idx]
    end = _window_end(phrases, idx, style.phrase_hold)
    fade_in = (t - p.start) / fade
    fade_out = (end - t) / fade
    return max(0.0, min(1.0, fade_in, fade_out))


def apply_opacity(layer: Image.Image, opacity: float) -> None:
    """Scale a rendered RGBA layer's alpha channel in place by `opacity`."""
    alpha = layer.getchannel("A").point(lambda v: int(v * opacity))
    layer.putalpha(alpha)


def draw_phrase(
    img: Image.Image,
    phrase: Phrase,
    active_word_idx: int,
    style: CaptionStyle,
    t: float,
) -> None:
    """Draw a single phrase onto img (which is RGBA, already cleared)."""
    draw = ImageDraw.Draw(img)
    font = get_font(style.font_path, style.font_size)
    emoji_font: Optional[EmojiFont] = load_emoji_font(
        style.emoji_font_path, style.font_size)

    space_w, _ = measure_word(font, " ")

    # ── compute layout: line widths & total block height ────────────────────
    line_widths = [line_width(font, line.words, space_w, emoji_font) for line in phrase.lines]
    line_h = int(style.font_size * style.line_spacing)
    total_h = line_h * len(phrase.lines)

    # vertical block placement based on anchor
    block_top = int(style.height * style.vertical_anchor - total_h / 2)

    # ── optional background box ─────────────────────────────────────────────
    if style.bg_enabled:
        max_w = max(line_widths) if line_widths else 0
        pad = style.bg_padding
        box_left = (style.width - max_w) // 2 - pad
        box_right = box_left + max_w + pad * 2
        box_top = block_top - pad
        box_bottom = block_top + total_h + pad
        draw.rounded_rectangle(
            [box_left, box_top, box_right, box_bottom],
            radius=style.bg_radius,
            fill=style.bg_color,
        )

    # ── draw each line ──────────────────────────────────────────────────────
    word_running_idx = 0  # index into phrase.all_words
    for line_idx, line in enumerate(phrase.lines):
        line_w = line_widths[line_idx]
        x = (style.width - line_w) // 2
        y = block_top + line_idx * line_h

        for w_idx, word in enumerate(line.words):
            is_active = (word_running_idx == active_word_idx)
            ww, wh = measure_word(font, word.text, emoji_font)

            # ── highlight: "box" mode ───────────────────────────────────────
            if is_active and style.highlight_mode == "box":
                pad = style.highlight_box_padding
                draw.rounded_rectangle(
                    [x - pad, y - pad // 2, x + ww + pad, y + wh + pad],
                    radius=8,
                    fill=style.highlight_box_color,
                )

            # ── choose text color ───────────────────────────────────────────
            color = style.highlight_color if is_active else style.text_color

            # ── entry animation: subtle pop when word becomes active ───────
            scale = 1.0
            if is_active:
                if style.entry_anim == "pop":
                    elapsed = t - word.start
                    if 0 <= elapsed < style.entry_anim_duration:
                        prog = elapsed / style.entry_anim_duration
                        scale = 1.0 + 0.18 * math.sin(prog * math.pi)
                if style.highlight_mode == "scale":
                    scale *= style.highlight_scale

            # ── render the word ────────────────────────────────────────────
            if abs(scale - 1.0) < 0.001:
                draw_text_with_stroke(draw, (x, y), word.text, font, color, style, emoji_font)
            else:
                draw_scaled_word(img, word.text, font, color, style, x, y, ww, wh, scale, emoji_font)

            x += ww + space_w
            word_running_idx += 1
