"""Export all screen alternatives with example context, without touching learning history."""

from pathlib import Path
from math import ceil
from PIL import Image, ImageDraw
from enki_core.config import Config, ROOT
from enki_core.designs import DESIGNS, font
from enki_core.render import Renderer

context = {
    "date": "2026-10-24",
    "weather": {"min": 7, "max": 14, "symbol": "sun"},
    "events": [
        {"title": title, "start": "2026-10-24T" + clock + ":00+02:00"}
        for title, clock in [("Coffee break", "16:00"), ("Japanese", "18:30"), ("Walk", "20:00")]
    ],
}
card = {"id": "preview:neko", "jp": "ねこ", "kanji": "猫", "reading": "neko", "meaning": "cat"}
data = ROOT / ".work/design-export"
data.mkdir(parents=True, exist_ok=True, mode=0o700)
r = Renderer(Config(data))
cellw, cellh, margin = 942, 388, 28
sheet = Image.new("RGB", (cellw * 3 + margin * 2, cellh * ceil(len(DESIGNS) / 3) + 130), "white")
draw = ImageDraw.Draw(sheet)
folder = str(ROOT / "enki/assets/production")
draw.text(
    (margin, 18), f"{len(DESIGNS)} screen directions", font=font(folder, "sans", 38), fill="black"
)
draw.text(
    (margin, 72),
    "Front · revealed · nothing due. Example weather and calendar. Each original screen is 600 × 600.",
    font=font(folder, "sans", 18),
    fill="black",
)
for i, design in enumerate(DESIGNS):
    x = margin + (i % 3) * cellw
    y = 128 + (i // 3) * cellh
    draw.text((x, y), design["name"], font=font(folder, "sans", 23), fill="black")
    for j, side in enumerate(["front", "back", "idle"]):
        f = r.frame(
            None if side == "idle" else card,
            "front" if side == "idle" else side,
            context,
            design["id"],
        )
        im = Image.open(r.frames / (f["id"] + ".png")).convert("RGB")
        im.save(data / f"{design['id']}-{side}.png")
        sheet.paste(im.resize((300, 300), Image.Resampling.LANCZOS), (x + j * 310, y + 42))
        draw.rectangle((x + j * 310, y + 42, x + j * 310 + 299, y + 341), outline="#bdbdbd")
    draw.text((x, y + 350), design["note"], font=font(folder, "sans", 15), fill="black")
output = Path.home() / "Downloads" / f"Enki-{len(DESIGNS)}-contrast-designs.png"
sheet.save(output)
print(output)
