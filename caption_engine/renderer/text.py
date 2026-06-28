"""Text measurement and drawing, with emoji-aware font switching."""
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from ..style import CaptionStyle
from ..transcriber import Word
from ..emoji import has_emoji, split_runs


def _iter_cells(text: str, emoji_font):
    """Yield (segment, is_emoji) cells for letter-spacing: each non-emoji
    character individually, each emoji run (which may be a multi-codepoint
    sequence) as one unit."""
    if emoji_font is None or not has_emoji(text):
        for ch in text:
            yield ch, False
        return
    for segment, is_emoji in split_runs(text):
        if is_emoji:
            yield segment, True
        else:
            for ch in segment:
                yield ch, False


def measure_word(
    font: ImageFont.FreeTypeFont,
    text: str,
    emoji_font=None,
    letter_spacing: int = 0,
) -> Tuple[int, int]:
    """Return (width, height) of a word, switching to emoji_font for emoji runs.

    `emoji_font` is an EmojiFont wrapper (loaded at a real strike, with a scale
    factor), so emoji runs are measured at their scaled display size.

    With `letter_spacing` > 0, an extra `letter_spacing` pixels is added between
    characters (not after the last one), matching draw_text_with_stroke.
    """
    if letter_spacing == 0:
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

    # letter-spaced path: advance each cell by the font's advance width (NOT the
    # ink bbox width — using the bbox drops side bearings and makes letters sit
    # slightly off) and insert spacing between cells.
    total_w, max_h, n = 0.0, 0, 0
    for segment, is_emoji in _iter_cells(text, emoji_font):
        if is_emoji:
            w, h = emoji_font.measure(segment)
        else:
            w = font.getlength(segment)
            bbox = font.getbbox(segment)
            h = bbox[3] - bbox[1]
        total_w += w + letter_spacing
        max_h = max(max_h, h)
        n += 1
    if n:
        total_w -= letter_spacing  # no trailing spacing after the last cell
    return int(round(total_w)), max_h


def line_width(
    font: ImageFont.FreeTypeFont,
    words: List[Word],
    space_w: int,
    emoji_font=None,
    letter_spacing: int = 0,
) -> int:
    if not words:
        return 0
    total = 0
    for i, w in enumerate(words):
        total += measure_word(font, w.text, emoji_font, letter_spacing)[0]
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
    ls = style.letter_spacing

    # fast path: no spacing and no emoji → draw the whole string at once so the
    # font's own kerning is preserved.
    if ls == 0 and (emoji_font is None or not has_emoji(text)):
        if style.text_stroke_width > 0:
            draw.text(pos, text, font=font, fill=color,
                      stroke_width=style.text_stroke_width,
                      stroke_fill=style.text_stroke_color)
        else:
            draw.text(pos, text, font=font, fill=color)
        return

    def _draw_seg(px, py, seg):
        if style.text_stroke_width > 0:
            draw.text((px, py), seg, font=font, fill=color,
                      stroke_width=style.text_stroke_width,
                      stroke_fill=style.text_stroke_color)
        else:
            draw.text((px, py), seg, font=font, fill=color)

    target = getattr(draw, "_image", None)
    x, y = pos
    # per-cell when letter-spacing is on; otherwise per emoji/text run
    cells = _iter_cells(text, emoji_font) if ls else split_runs(text)
    for segment, is_emoji in cells:
        if is_emoji:
            glyph = emoji_font.render(segment)
            if target is not None:
                target.alpha_composite(glyph, (int(x), int(y)))
            x += emoji_font.measure(segment)[0] + ls
        else:
            _draw_seg(x, y, segment)
            # advance by the glyph's advance width (preserves side bearings) so
            # the spacing between letters stays even
            x += font.getlength(segment) + ls


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
