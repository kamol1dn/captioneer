import json
import shutil
from pathlib import Path
root = Path(__file__).resolve().parents[2]
out = root / 'data/outputs/gashtak-preview'
out.mkdir(parents=True, exist_ok=True)
staged = root / 'graphics/public/_assets'
staged.mkdir(parents=True, exist_ok=True)
for font in ('Helvetica.ttf', 'Helvetica-Bold.ttf'):
    shutil.copy2(root / 'assets-fonts/helvetica' / font, staged / font)
examples = [
    dict(kind='book', title='So‘z erkinligi haqida so‘z', detail='Karim Bahriyev'),
    dict(kind='term', title='Axborot gigiyenasi', detail='Axborotni saralash, manbasini tekshirish va iste’molini me’yorlash.'),
    dict(kind='question', title='Fikringizni butunlay o‘zgartirgan voqea yoki kitob bo‘lganmi?'),
]
jobs = [dict(template='GashtakLowerThird', props=p, width=1920, height=1080, fps=30, frames=240, stillOnly=True, out=str(out / (p['kind']+'-alpha.png'))) for p in examples]
jobs += [dict(template='GashtakPreview', props={}, width=1280, height=720, fps=30, frames=450, codec='h264', concurrency=4, out=str(out/'gashtak-motion-preview.mp4'))]
(out/'jobs.json').write_text(json.dumps(dict(jobs=jobs), ensure_ascii=False, indent=2), encoding='utf-8')
print(out/'jobs.json')
