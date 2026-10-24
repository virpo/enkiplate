"""Render the selected theme and representative states without touching study history."""

import json
from pathlib import Path

from PIL import Image, ImageDraw
from enki_core.config import Config, ROOT
from enki_core.designs import font
from enki_core.paper_concepts import CARD, CONTEXT
from enki_core.render import Renderer

folder = ROOT / ".work/washi-ready"
folder.mkdir(parents=True, exist_ok=True)
renderer = Renderer(Config(folder))
fixtures = [
    ("Front", CARD, "front"),
    ("Revealed", CARD, "back"),
    ("Nothing due", None, "front"),
    (
        "Kanji",
        {"id": "proof:yama", "jp": "やま", "kanji": "山", "reading": "yama", "meaning": "mountain"},
        "back",
    ),
    (
        "Words",
        {
            "id": "proof:gakkou",
            "jp": "がっこう",
            "kanji": "学校",
            "reading": "gakkou",
            "meaning": "school",
        },
        "back",
    ),
    (
        "Sentences",
        {
            "id": "proof:sentence",
            "jp": "明日は電車で京都に行きます。",
            "reading": "ashita wa densha de kyouto ni ikimasu.",
            "meaning": "Tomorrow, I will go to Kyoto by train.",
        },
        "back",
    ),
]
sheet = Image.new("RGB", (1872, 1440), "white")
draw = ImageDraw.Draw(sheet)
fonts = str(ROOT / "enki/assets/production")
draw.text((24, 16), "Wave washi", font=font(fonts, "sans", 40), fill="black")
draw.text(
    (25, 75),
    "10% smaller text rectangle · native 600 × 600 screens · example appointments",
    font=font(fonts, "sans", 20),
    fill="black",
)
frames = []
for i, (label, card, side) in enumerate(fixtures):
    frame = renderer.frame(card, side, CONTEXT, "washi-wave")
    image = Image.open(renderer.frames / (frame["id"] + ".png"))
    image.save(folder / (label.lower().replace(" ", "-") + ".png"))
    x, y = 24 + i % 3 * 624, 132 + i // 3 * 650
    draw.text((x, y), label, font=font(fonts, "sans", 23), fill="black")
    sheet.paste(image.convert("RGB"), (x, y + 36))
    draw.rectangle((x, y + 36, x + 599, y + 635), outline="#bbb")
    frames.append(
        {
            "label": label,
            "bytes": frame["bytes"],
            "compressed_bytes": frame["compressed_bytes"],
            "crc32": frame["crc32"],
        }
    )
output = Path.home() / "Downloads/Enki-Wave-washi-ready.png"
sheet.save(output)
(folder / "verification.json").write_text(json.dumps(frames, indent=2) + "\n")
before_path = ROOT / ".work/proof/washi-pattern-before.png"
if before_path.exists():
    before = Image.open(before_path).convert("RGB")
    after = Image.open(folder / "revealed.png").convert("RGB")
    comparison = Image.new("RGB", (1200, 600), "white")
    comparison.paste(before, (0, 0))
    comparison.paste(after, (600, 0))
    comparison.save(ROOT / ".work/proof/washi-inset-before-after.png")
print(output)
print(json.dumps(frames))
