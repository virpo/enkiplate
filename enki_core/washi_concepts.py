"""🪨 Real material plates under the existing Japanese study interface."""

from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageChops

from .config import ROOT
from .designs import render
from .paper_concepts import CARD, CONTEXT

ASSETS = ROOT / "enki/assets/objects/washi"
CONCEPTS = json.loads((ASSETS.parent / "washi-prompts.json").read_text())["variants"]
# 90% of Large print's 514 × 303 study box, centred in the same position.
# This gives the text breathing room inside the torn paper without moving controls.
TEXT_BOX = (69, 160, 462, 273)


def render_screen(card, side, context, concept="pattern", *, font_dir=None, assets=None):
    if side not in {"front", "back"} or concept not in {c["id"] for c in CONCEPTS}:
        raise ValueError("Unknown washi concept or side")
    # The generated bitmap is a material widget, clipped to the word area.
    # Header, actual type and touch controls are drawn by the existing renderer.
    material_dir = Path(assets) / "washi" if assets is not None else ASSETS
    plate = (
        Image.open(
            material_dir / ("pattern-v3.png" if concept == "pattern" else f"{concept}-v2.png")
        )
        .convert("L")
        .resize((600, 600), Image.Resampling.LANCZOS)
    )
    surface = Image.new("L", (600, 600), 255)
    surface.paste(plate.crop((0, 128, 600, 474)), (0, 128))
    ui = render(
        "large",
        card,
        side,
        context,
        font_dir or ROOT / "enki/assets/production",
        assets or ASSETS.parent,
        text_box=TEXT_BOX,
    )
    return ImageChops.darker(ui, surface)


def preview(concept, side="back"):
    image = render_screen(CARD, side, CONTEXT, concept)
    palette = Image.new("P", (1, 1))
    tones = [round(i * 255 / 7) for i in range(8)]
    palette.putpalette([c for tone in tones for c in (tone, tone, tone)] + [255] * (768 - 24))
    return (
        image.convert("RGB")
        .quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        .convert("L")
    )
