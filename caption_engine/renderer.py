"""Frame renderer: takes Phrases + CaptionStyle -> transparent ProRes 4444 .mov.

Pipeline:
  for each frame:
     find active phrase
     find active word in phrase
     draw lines centered around vertical_anchor
     draw active word with highlight (color/scale/box)
     pipe RGBA frame to ffmpeg stdin
  ffmpeg encodes to ProRes 4444 with alpha channel

Why ProRes 4444? It's the de-facto standard for alpha-channel video in pro
NLEs (Premiere, Resolve, Final Cut). Editors can drop the .mov on a track and
see-through transparency just works.
"""
from __future__ import annotations
import re
import subprocess
import math
from typing import List, Optional, Callable, Tuple
from PIL import Image, ImageDraw, ImageFont

# Matches emoji characters (supplementary plane + misc symbols + variation selector)
_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FFFF"
    r"\U00002600-\U000027BF"
    r"️]+"
    r"(?:‍[\U0001F000-\U0001FFFF\U00002600-\U000027BF️]+)*"
)


def _has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def _split_runs(text: str) -> List[Tuple[str, bool]]:
    """Split text into (segment, is_emoji) pairs for font-switching."""
    runs: List[Tuple[str, bool]] = []
    pos = 0
    for m in _EMOJI_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False))
        runs.append((m.group(), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return runs or [(text, False)]

from .style import CaptionStyle
from .layout import Phrase, Line, find_active_word_index
from .transcriber import Word


# ─── Font cache (loading fonts is slow; we do it once per size) ─────────────
_FONT_CACHE: dict = {}


# Valid bitmap strike sizes for sbix fonts (e.g. AppleColorEmoji)
_SBIX_SIZES = [20, 32, 40, 48, 64, 96, 160]


def _get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _FONT_CACHE:
        if not path:
            raise FileNotFoundError(
                "No font found automatically. Set style.font_path to a .ttf/.otf file.\n"
                "  Windows: C:\\Windows\\Fonts\\arialbd.ttf\n"
                "  macOS:   /Library/Fonts/Arial Bold.ttf\n"
                "  Linux:   /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )
        try:
            _FONT_CACHE[key] = ImageFont.truetype(path, size)
        except OSError as exc:
            if "invalid pixel size" in str(exc).lower():
                # Bitmap-only (sbix) font — snap to nearest valid strike size
                snapped = min(_SBIX_SIZES, key=lambda s: abs(s - size))
                try:
                    _FONT_CACHE[key] = ImageFont.truetype(path, snapped)
                except OSError:
                    raise FileNotFoundError(
                        f"Font file not readable: {path!r}\n"
                        "Set style.font_path to a valid .ttf/.otf file."
                    ) from None
            else:
                raise FileNotFoundError(
                    f"Font file not readable: {path!r}\n"
                    "Set style.font_path to a valid .ttf/.otf file."
                ) from None
    return _FONT_CACHE[key]


def _measure_word(
    font: ImageFont.FreeTypeFont,
    text: str,
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
) -> Tuple[int, int]:
    """Return (width, height) of a word, switching to emoji_font for emoji runs."""
    if emoji_font is None or not _has_emoji(text):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    total_w, max_h = 0, 0
    for segment, is_emoji in _split_runs(text):
        f = emoji_font if is_emoji else font
        bbox = f.getbbox(segment)
        total_w += bbox[2] - bbox[0]
        max_h = max(max_h, bbox[3] - bbox[1])
    return total_w, max_h


def _line_width(
    font: ImageFont.FreeTypeFont,
    words: List[Word],
    space_w: int,
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
) -> int:
    if not words:
        return 0
    total = 0
    for i, w in enumerate(words):
        total += _measure_word(font, w.text, emoji_font)[0]
        if i < len(words) - 1:
            total += space_w
    return total


def _find_active_phrase(
    phrases: List[Phrase], t: float, hold: float = 0.0
) -> Optional[int]:
    """Find phrase active at time t. Returns None if in a gap.

    Each phrase stays active for `hold` seconds past its last word so its final
    frame is held across the gap before the next phrase (instead of blinking
    off). The hold is clamped to the next phrase's start so the two never
    overlap.
    """
    for i, p in enumerate(phrases):
        end = p.end + hold
        if i + 1 < len(phrases):
            end = min(end, phrases[i + 1].start)
        if p.start <= t <= end:
            return i
    return None


def _draw_phrase(
    img: Image.Image,
    phrase: Phrase,
    active_word_idx: int,
    style: CaptionStyle,
    t: float,
) -> None:
    """Draw a single phrase onto img (which is RGBA, already cleared)."""
    draw = ImageDraw.Draw(img)
    font = _get_font(style.font_path, style.font_size)
    emoji_font: Optional[ImageFont.FreeTypeFont] = None
    if style.emoji_font_path:
        try:
            emoji_font = _get_font(style.emoji_font_path, style.font_size)
        except FileNotFoundError:
            pass

    space_w, _ = _measure_word(font, " ")

    # ── compute layout: line widths & total block height ────────────────────
    line_widths = [_line_width(font, line.words, space_w, emoji_font) for line in phrase.lines]
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
            ww, wh = _measure_word(font, word.text, emoji_font)

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
                _draw_text_with_stroke(draw, (x, y), word.text, font, color, style, emoji_font)
            else:
                _draw_scaled_word(img, word.text, font, color, style, x, y, ww, wh, scale, emoji_font)

            x += ww + space_w
            word_running_idx += 1


def _draw_text_with_stroke(
    draw, pos, text, font, color, style: CaptionStyle,
    emoji_font: Optional[ImageFont.FreeTypeFont] = None,
):
    """Draw text with optional stroke, switching to emoji_font for emoji runs."""
    if emoji_font is None or not _has_emoji(text):
        if style.text_stroke_width > 0:
            draw.text(pos, text, font=font, fill=color,
                      stroke_width=style.text_stroke_width,
                      stroke_fill=style.text_stroke_color)
        else:
            draw.text(pos, text, font=font, fill=color)
        return

    x, y = pos
    for segment, is_emoji in _split_runs(text):
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


def _draw_scaled_word(
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
    _draw_text_with_stroke(sub_draw, (pad, pad), text, font, color, style, emoji_font)

    new_w = max(1, int(sub_w * scale))
    new_h = max(1, int(sub_h * scale))
    sub = sub.resize((new_w, new_h), Image.LANCZOS)

    paste_x = x + ww // 2 - new_w // 2
    paste_y = y + wh // 2 - new_h // 2
    img.alpha_composite(sub, (paste_x, paste_y))


# ─── Main public function ──────────────────────────────────────────────────
def render_to_mov(
    phrases: List[Phrase],
    style: CaptionStyle,
    output_path: str,
    duration: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Render all phrases to a transparent ProRes 4444 .mov.

    Args:
        phrases: result of layout.build_phrases()
        style: CaptionStyle to use
        output_path: .mov file path
        duration: total clip duration in seconds. If None, uses last word end.
        progress_cb: optional callback(current_frame, total_frames)
    """
    if duration is None:
        # Tail the clip by the hold so the last phrase's held frame is included.
        tail = max(style.phrase_hold, 0.5)
        duration = phrases[-1].end + tail if phrases else 1.0
    total_frames = int(duration * style.fps)

    # ── spin up ffmpeg ──────────────────────────────────────────────────────
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{style.width}x{style.height}",
        "-pix_fmt", "rgba",
        "-r", str(style.fps),
        "-i", "-",                       # stdin
        "-c:v", "prores_ks",
        "-profile:v", "4444",            # ProRes 4444 supports alpha
        "-pix_fmt", "yuva444p10le",
        "-vendor", "ap10",
        "-an",
        output_path,
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE
    )

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / style.fps
            img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))

            phrase_idx = _find_active_phrase(phrases, t, style.phrase_hold)
            if phrase_idx is not None:
                phrase = phrases[phrase_idx]
                active_word = find_active_word_index(phrase, t)
                _draw_phrase(img, phrase, active_word, style, t)

            proc.stdin.write(img.tobytes())

            if progress_cb and frame_idx % style.fps == 0:
                progress_cb(frame_idx, total_frames)
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="ignore")
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"ffmpeg failed (code {ret}):\n{stderr[-2000:]}")

    if progress_cb:
        progress_cb(total_frames, total_frames)
