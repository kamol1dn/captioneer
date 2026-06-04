"""Text measurement and drawing, with emoji-aware font switching."""
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from ..style import CaptionStyle
from ..transcriber import Word
from ..emoji import has_emoji, split_runs


def measure_word(
    font: ImageFont.FreeTypeFont,
    text: str,
    emoji_font=None,
) -> Tuple[int, int]:
    """Return (width, height) of a word, switching to emoji_font for emoji runs.

    `emoji_font` is an EmojiFont wrapper (loaded at a real strike, with a scale
    factor), so emoji runs are measured at their scaled display size.
    """
    if emoji_font is None or not has_emoji(text):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    total_w, max_h = 0, 0
    for segment, is_emoji in split_runs(text):
        if is_emoji:
            w, h = emoji_font.measure(segment)
        else:
            bbox = font.getbbox(segment)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        total_w += w
        max_h = max(max_h, h)
    return total_w, max_h


def line_width(
    font: ImageFont.FreeTypeFont,
    words: List[Word],
    space_w: int,
    emoji_font=None,
) -> int:
    if not words:
        return 0
    total = 0
    for i, w in enumerate(words):
        total += measure_word(font, w.text, emoji_font)[0]
        if i < len(words) - 1:
            total += space_w
    return total


def draw_text_with_stroke(
    draw, pos, text, font, color, style: CaptionStyle,
    emoji_font=None,
):
    """Draw text with optional stroke, switching to emoji_font for emoji runs.

    Emoji runs are bitmap glyphs rendered at the font's real strike and scaled
    to the display size (see EmojiFont), then alpha-composited onto the target
    image — PIL can't draw a bitmap-emoji font at an arbitrary pixel size.
    """
    if emoji_font is None or not has_emoji(text):
        if style.text_stroke_width > 0:
            draw.text(pos, text, font=font, fill=color,
                      stroke_width=style.text_stroke_width,
                      stroke_fill=style.text_stroke_color)
        else:
            draw.text(pos, text, font=font, fill=color)
        return

    target = getattr(draw, "_image", None)
    x, y = pos
    for segment, is_emoji in split_runs(text):
        if is_emoji:
            glyph = emoji_font.render(segment)
            if target is not None:
                target.alpha_composite(glyph, (int(x), int(y)))
            x += emoji_font.measure(segment)[0]
        else:
            if style.text_stroke_width > 0:
                draw.text((x, y), segment, font=font, fill=color,
                          stroke_width=style.text_stroke_width,
                          stroke_fill=style.text_stroke_color)
            else:
                draw.text((x, y), segment, font=font, fill=color)
            seg_bbox = font.getbbox(segment)
            x += seg_bbox[2] - seg_bbox[0]


def draw_scaled_word(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    color,
    style: CaptionStyle,
    x: int,
    y: int,
    ww: int,
    wh: int,
    scale: float,
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
) -> None:
    """Render the word to a sub-image, scale it, and paste it back centered."""
    pad = style.text_stroke_width * 2 + 4
    sub_w, sub_h = ww + pad * 2, wh + pad * 2
    sub = Image.new("RGBA", (sub_w, sub_h), (0, 0, 0, 0))
    sub_draw = ImageDraw.Draw(sub)
    draw_text_with_stroke(sub_draw, (pad, pad), text, font, color, style, emoji_font)

    new_w = max(1, int(sub_w * scale))
    new_h = max(1, int(sub_h * scale))
    sub = sub.resize((new_w, new_h), Image.LANCZOS)

    paste_x = x + ww // 2 - new_w // 2
    paste_y = y + wh // 2 - new_h // 2
    img.alpha_composite(sub, (paste_x, paste_y))
