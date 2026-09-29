"""Composite rendered alpha stills over the supplied frame for design review."""
from pathlib import Path
from PIL import Image
root = Path(__file__).resolve().parents[2]
out = root / 'data/outputs/gashtak-preview'
bg = Image.open(root / 'graphics/public/_assets/gashtak-reference.jpg').convert('RGBA').resize((1920, 1080), Image.Resampling.LANCZOS)
for kind in ('book', 'term', 'question'):
    overlay = Image.open(out / f'{kind}-alpha.png').convert('RGBA')
    assert overlay.size == bg.size
    assert overlay.getpixel((0, 0))[3] == 0, 'Overlay background must be transparent'
    assert overlay.getextrema()[3][1] > 0, 'Overlay must contain visible artwork'
    Image.alpha_composite(bg, overlay).convert('RGB').save(out / f'{kind}-preview.jpg', quality=94)
    print(f'{kind}: alpha verified, composite saved')
