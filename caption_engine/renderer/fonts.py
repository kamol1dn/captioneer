"""Font loading and caching for the renderer.

Loading fonts is slow, so each (path, size) is loaded once and cached.
"""
from PIL import ImageFont

# Font cache: (path, size) -> FreeTypeFont
_FONT_CACHE: dict = {}

# Valid bitmap strike sizes for sbix fonts (e.g. AppleColorEmoji)
_SBIX_SIZES = [20, 32, 40, 48, 64, 96, 160]


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
