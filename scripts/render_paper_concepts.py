"""Export ten paper concepts as native screens, a static picker and one share image."""

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
from enki_core.config import ROOT
from enki_core.designs import font
from enki_core.paper_concepts import CONCEPTS, preview

folder = ROOT / ".work/paper-concepts"
folder.mkdir(parents=True, exist_ok=True)
export = []
sheet = Image.new("RGB", (1320, 2050), "white")
draw = ImageDraw.Draw(sheet)
fonts = str(ROOT / "enki/assets/production")
draw.text((28, 15), "A little paper. Still 08.", font=font(fonts, "sans", 38), fill="black")
draw.text(
    (29, 68),
    "10 concepts · front + revealed · example weather and calendar",
    font=font(fonts, "sans", 18),
    fill="black",
)
for i, concept in enumerate(CONCEPTS):
    entry = dict(concept)
    x, y = 28 + (i % 2) * 652, 123 + (i // 2) * 382
    draw.text((x, y), concept["name"], font=font(fonts, "sans", 23), fill="black")
    for j, side in enumerate(("front", "back")):
        image = preview(concept["id"], side)
        image.save(folder / f"{concept['id']}-{side}.png")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        entry[side] = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        box = (x + j * 309, y + 39)
        sheet.paste(image.convert("RGB").resize((300, 300), Image.Resampling.LANCZOS), box)
        draw.rectangle((*box, box[0] + 299, box[1] + 299), outline="#b6b6b6")
    draw.text((x, y + 346), concept["note"], font=font(fonts, "sans", 14), fill="black")
    export.append(entry)
(ROOT / "web/paper-concepts.json").write_text(
    json.dumps(export, ensure_ascii=False, separators=(",", ":"))
)
output = Path.home() / "Downloads/Enki-10-paper-concepts.png"
sheet.save(output)
print(output)
