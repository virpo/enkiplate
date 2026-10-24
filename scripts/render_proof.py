"""Render fixture examples. Calendar rows here are layout fixtures, never production data."""

from pathlib import Path
from PIL import Image, ImageDraw
from enki_core.config import Config
from enki_core.render import Renderer

config = Config.load()
renderer = Renderer(config)
context = {
    "date": "2026-10-24",
    "weather": {"min": 4, "max": 14, "symbol": "cloud"},
    "events": [
        {"title": "Coffee break", "start": "2026-10-24T14:00:00+00:00"},
        {"title": "Japanese", "start": "2026-10-24T16:30:00+00:00"},
        {"title": "Walk", "start": "2026-10-24T18:00:00+00:00"},
    ],
}
cards = [
    {"id": "fixture:kana", "jp": "あ", "reading": "a", "meaning": ""},
    {"id": "fixture:word", "jp": "ねこ", "reading": "neko", "meaning": "cat"},
    {"id": "fixture:kanji", "jp": "電車", "reading": "densha", "meaning": "train"},
]
out = Path(".work/proof")
out.mkdir(parents=True, exist_ok=True)
montage = Image.new("L", (1800, 1235), 244)
draw = ImageDraw.Draw(montage)
draw.text((20, 10), "Layout fixtures. Eight grayscale levels. Actual output is 600 x 600.", fill=0)
for i, card in enumerate(cards):
    for j, side in enumerate(("front", "back")):
        frame = renderer.frame(card, side, context)
        im = Image.open(config.data / "frames" / f"{frame['id']}.png")
        im.save(out / f"{i}-{side}.png")
        montage.paste(im, (i * 600, 35 + j * 600))
montage.save(out / "six-states.png")
