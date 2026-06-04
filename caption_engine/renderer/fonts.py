"""Font loading and caching for the renderer.

Loading fonts is slow, so each (path, size) is loaded once and cached.
"""
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont

# Font cache: (path, size) -> FreeTypeFont
_FONT_CACHE: dict = {}

# Color-emoji fonts (sbix/CBDT) are bitmap-only: they render *only* at their
# baked-in strike sizes and raise "invalid pixel size" at any other size. The
# bundled AppleColorEmoji-Windows.ttf, for instance, has a single 96px strike.
# We can't know a font's strikes up front, so we probe — cheap candidates first,
# full scan as a fallback — and cache the result per path.
_STRIKE_CACHE: dict = {}
_STRIKE_CANDIDATES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 137, 160, 256]


def _available_strikes(path: str) -> List[int]:
    """Return the bitmap strike sizes a (color) font actually supports."""
    if path not in _STRIKE_CACHE:
        strikes = [s for s in _STRIKE_CANDIDATES if _loads_at(path, s)]
        if not strikes:
            strikes = [s for s in range(8, 257) if _loads_at(path, s)]
        _STRIKE_CACHE[path] = strikes
    return _STRIKE_CACHE[path]


def _loads_at(path: str, size: int) -> bool:
    try:
        ImageFont.truetype(path, size)
        return True
    except OSError:
        return False


class EmojiFont:
    """A color-emoji font loaded at a real strike, with a scale factor to reach
    the requested display size. Bitmap emoji can't be drawn at arbitrary sizes,
    so we render at the strike and resize the glyph to match the text.
    """
    __slots__ = ("font", "scale")

    def __init__(self, font: ImageFont.FreeTypeFont, scale: float):
        self.font = font
        self.scale = scale

    def measure(self, text: str) -> tuple:
        """(width, height) of `text` at the scaled display size."""
        l, t, r, b = self.font.getbbox(text)
        return (int(round((r - l) * self.scale)),
                int(round((b - t) * self.scale)))

    def render(self, text: str) -> Image.Image:
        """An RGBA image of `text`, drawn at the strike then scaled to size.

        Drawn from origin (0,0) so compositing at a pen position reproduces the
        same placement PIL's draw.text would, only scaled.
        """
        bbox = self.font.getbbox(text)
        w, h = max(1, bbox[2]), max(1, bbox[3])
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), text, font=self.font, embedded_color=True)
        if self.scale != 1.0:
            canvas = canvas.resize(
                (max(1, int(round(w * self.scale))), max(1, int(round(h * self.scale)))),
                Image.LANCZOS,
            )
        return canvas


def load_emoji_font(path: str, target_size: int) -> Optional[EmojiFont]:
    """Load a color-emoji font sized to `target_size`.

    If the font is scalable (or already has a strike at the exact size) it's used
    at 1:1; otherwise we snap to its nearest available strike and carry a scale
    factor so the glyph is resized down/up to `target_size`. Returns None if the
    path is empty or the font has no usable strike.
    """
    if not path:
        return None
    if _loads_at(path, target_size):
        return EmojiFont(_cached_truetype(path, target_size), 1.0)
    strikes = _available_strikes(path)
    if not strikes:
        return None
    strike = min(strikes, key=lambda s: abs(s - target_size))
    return EmojiFont(_cached_truetype(path, strike), target_size / strike)


def _cached_truetype(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


def get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
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
                # Bitmap-only (sbix/CBDT) font — snap to its nearest real strike.
                # (Color emoji should go through load_emoji_font, which also
                # scales the glyph; this is a best-effort fallback for callers
                # that route a bitmap font through get_font directly.)
                strikes = _available_strikes(path)
                if strikes:
                    snapped = min(strikes, key=lambda s: abs(s - size))
                    _FONT_CACHE[key] = ImageFont.truetype(path, snapped)
                else:
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
