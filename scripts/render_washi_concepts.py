"""Build a read-only gallery and share sheet from the ten generated material plates."""

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
from enki_core.config import ROOT
from enki_core.designs import font
from enki_core.washi_concepts import CONCEPTS, preview

folder = ROOT / ".work/washi-concepts"
folder.mkdir(parents=True, exist_ok=True)
export = []
sheet = Image.new("RGB", (2036, 1100), "white")
draw = ImageDraw.Draw(sheet)
fonts = str(ROOT / "enki/assets/production")
draw.text((28, 16), "Paper + washi. Ten ways.", font=font(fonts, "sans", 40), fill="black")
draw.text(
    (29, 75),
    "Top left + bottom right. Photorealistic material studies, rendered for 600 × 600 e-paper. Sample appointments.",
    font=font(fonts, "sans", 19),
    fill="black",
)
for i, concept in enumerate(CONCEPTS):
    entry = {k: concept[k] for k in ("id", "name", "note")}
    x, y = 28 + (i % 5) * 401, 138 + (i // 5) * 472
    draw.text((x, y), concept["name"], font=font(fonts, "sans", 22), fill="black")
    for side in ("front", "back"):
        image = preview(concept["id"], side)
        image.save(folder / f"{concept['id']}-{side}.png")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        entry[side] = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        if side == "back":
            box = (x, y + 41)
            sheet.paste(image.convert("RGB").resize((376, 376), Image.Resampling.LANCZOS), box)
            draw.rectangle((*box, box[0] + 375, box[1] + 375), outline="#b6b6b6")
    draw.text((x, y + 428), concept["note"], font=font(fonts, "sans", 13), fill="black")
    export.append(entry)
(ROOT / "web/washi-concepts.json").write_text(
    json.dumps(export, ensure_ascii=False, separators=(",", ":"))
)
output = Path.home() / "Downloads/Enki-10-real-paper-washi.png"
sheet.save(output)
print(output)
