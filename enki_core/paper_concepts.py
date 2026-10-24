"""🪨 Paper studies over the selected Large print screen. No live data or state."""

from __future__ import annotations

import random
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .config import ROOT
from .designs import render

CONCEPTS = [
    {
        "id": "deckle",
        "name": "01 · A single sheet",
        "note": "White paper. Torn edges. Just enough shadow.",
    },
    {
        "id": "strip",
        "name": "02 · Japanese on paper",
        "note": "Only the Japanese sits on a torn strip.",
    },
    {
        "id": "scrap",
        "name": "03 · A kanji scrap",
        "note": "A small piece of paper for the new thing you’re learning.",
    },
    {
        "id": "index",
        "name": "04 · Study card",
        "note": "A clean index card with a little printed corner detail.",
    },
    {
        "id": "notebook",
        "name": "05 · From a notebook",
        "note": "A torn binding edge. White space everywhere else.",
    },
    {
        "id": "fold",
        "name": "06 · Folded corner",
        "note": "One crisp fold makes the paper feel tangible.",
    },
    {
        "id": "slips",
        "name": "07 · Two pieces",
        "note": "Japanese on one piece. Its answer on another.",
    },
    {
        "id": "stack",
        "name": "08 · A little stack",
        "note": "Three white cards. Thin edges give them depth.",
    },
    {"id": "pin", "name": "09 · One pin", "note": "One small pin anchors the white paper."},
    {
        "id": "tape",
        "name": "10 · Black washi",
        "note": "A torn white sheet held by a small piece of black tape.",
    },
]

CONTEXT = {
    "date": "2026-10-24",
    "weather": {"min": 7, "max": 14, "symbol": "sun"},
    "events": [
        {"title": title, "start": "2026-10-24T" + clock + ":00+02:00"}
        for title, clock in [("Coffee break", "16:00"), ("Japanese", "18:30"), ("Walk", "20:00")]
    ],
}
CARD = {"id": "paper:neko", "jp": "ねこ", "kanji": "猫", "reading": "neko", "meaning": "cat"}


def outline(box, seed, torn=("bottom",)):
    x, y, w, h = box
    rng = random.Random(seed)
    points = []
    for edge, length in [("top", w), ("right", h), ("bottom", w), ("left", h)]:
        steps = list(range(0, length, 5)) + [length]
        for i in steps:
            shift = rng.choice([-2, -1, 0, 0, 1, 2, 3]) if edge in torn else 0
            if edge == "top":
                points.append((x + i, y + shift))
            elif edge == "right":
                points.append((x + w + shift, y + i))
            elif edge == "bottom":
                points.append((x + w - i, y + h + shift))
            else:
                points.append((x + shift, y + h - i))
    return points


def sheet(image, box, seed=1, torn=("bottom",), shadow=(3, 4), edge=109):
    points = outline(box, seed, torn)
    shade = Image.new("L", image.size, 255)
    d = ImageDraw.Draw(shade)
    sx, sy = shadow
    d.polygon([(x + sx, y + sy) for x, y in points], fill=182)
    shade = shade.filter(ImageFilter.GaussianBlur(1.15))
    image.paste(ImageChops.darker(image, shade))
    d = ImageDraw.Draw(image)
    d.polygon(points, fill=255)
    d.line(points + points[:1], fill=edge, width=1)
    return d


def surface(concept, side):
    image = Image.new("L", (600, 600), 255)
    if concept == "deckle":
        sheet(image, (30, 143, 538, 311), 13, ("top", "bottom", "left", "right"))
    elif concept == "strip":
        height = 310 if side == "front" else 193
        sheet(image, (9, 143, 581, height), 41, ("left", "right", "bottom"), shadow=(2, 3))
    elif concept == "scrap":
        y, height = (364, 87) if side == "front" else (260, 74)
        sheet(
            image,
            (232, y, 136, height),
            21,
            ("top", "bottom", "left", "right"),
            shadow=(2, 3),
            edge=73,
        )
    elif concept == "index":
        d = sheet(image, (29, 142, 540, 312), 1, (), shadow=(2, 4), edge=73)
        d.line((44, 153, 73, 153), fill=0, width=2)
        d.line((44, 153, 44, 171), fill=0, width=2)
        d.line((525, 442, 554, 442), fill=0, width=2)
        d.line((554, 424, 554, 442), fill=0, width=2)
    elif concept == "notebook":
        d = sheet(image, (33, 143, 535, 311), 19, ("left", "bottom"), shadow=(2, 3))
        d.line((61, 148, 61, 444), fill=182, width=1)
        for y in range(162, 444, 33):
            d.ellipse((27, y, 40, y + 11), fill=255, outline=109, width=1)
            d.line((31, y + 3, 35, y + 3), fill=255, width=3)
    elif concept == "fold":
        d = sheet(image, (30, 143, 540, 311), 1, (), shadow=(3, 4), edge=73)
        # Erase the flat corner, then make a folded triangle with a hard crease.
        d.polygon([(540, 142), (574, 142), (574, 176)], fill=255)
        d.line((540, 143, 570, 173, 570, 454), fill=73, width=1)
        d.polygon([(540, 143), (540, 173), (570, 173)], fill=219, outline=73)
        d.line((540, 173, 568, 173), fill=36, width=2)
    elif concept == "slips":
        if side == "front":
            sheet(image, (31, 144, 538, 203), 16, ("bottom",), shadow=(2, 3))
            sheet(image, (218, 362, 164, 90), 26, ("top", "bottom"), shadow=(2, 3))
        else:
            sheet(image, (31, 143, 538, 189), 16, ("bottom",), shadow=(2, 3))
            sheet(image, (110, 337, 380, 117), 26, ("top", "bottom"), shadow=(2, 3))
    elif concept == "stack":
        sheet(image, (39, 153, 532, 310), 1, (), shadow=(2, 3), edge=109)
        sheet(image, (32, 148, 533, 310), 1, (), shadow=(2, 3), edge=73)
        sheet(image, (25, 142, 534, 311), 5, ("bottom",), shadow=(2, 3), edge=109)
    elif concept == "pin":
        d = sheet(image, (31, 144, 538, 310), 36, ("bottom",), shadow=(2, 4))
        d.ellipse((539, 150, 554, 165), fill=182)
        d.ellipse((536, 147, 551, 162), fill=0)
        d.ellipse((540, 150, 543, 153), fill=255)
    elif concept == "tape":
        d = sheet(image, (31, 145, 538, 308), 24, ("bottom", "left", "right"), shadow=(2, 4))
        # Small, ragged-ended washi. No translucent gray overlay on the text.
        d.polygon(
            [
                (258, 133),
                (342, 136),
                (339, 141),
                (343, 146),
                (338, 151),
                (340, 157),
                (256, 154),
                (259, 149),
                (254, 144),
                (260, 139),
            ],
            fill=0,
        )
    else:
        raise ValueError("Unknown paper concept")
    return image


def preview(concept, side="back", card=None, context=None):
    if side not in {"front", "back"}:
        raise ValueError("Unknown card side")
    base = render(
        "large",
        card or CARD,
        side,
        context or CONTEXT,
        ROOT / "enki/assets/production",
        ROOT / "enki/assets/objects",
    )
    image = ImageChops.darker(base, surface(concept, side))
    palette = Image.new("P", (1, 1))
    tones = [round(i * 255 / 7) for i in range(8)]
    palette.putpalette([c for tone in tones for c in (tone, tone, tone)] + [255] * (768 - 24))
    return (
        image.convert("RGB")
        .quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        .convert("L")
    )
