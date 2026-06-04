"""Text measurement and drawing, with emoji-aware font switching."""
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from ..style import CaptionStyle
from ..transcriber import Word
from ..emoji import has_emoji, split_runs


def measure_word(
    font: ImageFont.FreeTypeFont,
    text: str,
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
) -> Tuple[int, int]:
    """Return (width, height) of a word, switching to emoji_font for emoji runs."""
    if emoji_font is None or not has_emoji(text):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    total_w, max_h = 0, 0
    for segment, is_emoji in split_runs(text):
        f = emoji_font if is_emoji else font
        bbox = f.getbbox(segment)
        total_w += bbox[2] - bbox[0]
        max_h = max(max_h, bbox[3] - bbox[1])
    return total_w, max_h


def line_width(
    font: ImageFont.FreeTypeFont,
    words: List[Word],
    space_w: int,
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
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
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
):
    """Draw text with optional stroke, switching to emoji_font for emoji runs."""
    if emoji_font is None or not has_emoji(text):
        if style.text_stroke_width > 0:
            draw.text(pos, text, font=font, fill=color,
                      stroke_width=style.text_stroke_width,
                      stroke_fill=style.text_stroke_color)
        else:
            draw.text(pos, text, font=font, fill=color)
        return

    x, y = pos
    for segment, is_emoji in split_runs(text):
        f = emoji_font if is_emoji else font
        if is_emoji:
            try:
                draw.text((x, y), segment, font=f, embedded_color=True)
            except TypeError:
                draw.text((x, y), segment, font=f, fill=color)
        else:
            if style.text_stroke_width > 0:
                draw.text((x, y), segment, font=f, fill=color,
                          stroke_width=style.text_stroke_width,
                          stroke_fill=style.text_stroke_color)
            else:
                draw.text((x, y), segment, font=f, fill=color)
        seg_bbox = f.getbbox(segment)
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
