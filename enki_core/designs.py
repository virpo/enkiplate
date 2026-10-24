"""Black-and-white screen alternatives. Previews and hardware share these pixels/hit areas."""

from __future__ import annotations
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
import math
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

DESIGNS = [
    dict(id="clear", name="01 · Clear", note="White space. Bold type. Obvious buttons."),
    dict(id="terminal", name="02 · Terminal", note="A quiet white terminal with crisp frames."),
    dict(id="buddy", name="03 · Little friend", note="A happy pixel cat beside the card."),
    dict(id="index", name="04 · Index card", note="Typewriter rhythm and simple paper rules."),
    dict(id="night", name="05 · Night console", note="White ink on black. Maximum contrast."),
    dict(id="stack", name="06 · Big targets", note="Three full-width grading buttons."),
    dict(id="board", name="07 · Noticeboard", note="Left-aligned type and a small happy robot."),
    dict(id="large", name="08 · Large print", note="Bigger answers and two-line button labels."),
    dict(id="friendly", name="09 · Friendly terminal", note="An ASCII smile and a calm console."),
    dict(id="pixel", name="10 · Pocket game", note="Pixel corners, chunky keys, happy companion."),
    dict(
        id="paperlight",
        name="11 · Cutout, daylight",
        note="Lighter desk. White torn header. Bigger black pieces.",
    ),
    dict(
        id="paperstack",
        name="12 · Cutout, big pieces",
        note="White paper header and full-width tactile buttons.",
    ),
    dict(
        id="paperwhite",
        name="13 · Cutout, white keys",
        note="Separate torn notes and white button faces.",
    ),
    dict(
        id="washi-wave",
        name="Wave washi",
        note="White paper, wave-patterned tape and generous text margins.",
    ),
]
IDS = tuple(d["id"] for d in DESIGNS)
MONO = {"terminal", "index", "night", "friendly", "pixel"}
MATERIAL = {"paperlight", "paperstack", "paperwhite"}
STACKED = {"stack", "paperstack"}
AVATAR = {"buddy": "cat", "board": "robot", "friendly": "ascii", "pixel": "robot", "night": "ascii"}


@lru_cache(maxsize=160)
def font(folder: str, kind: str, size: int):
    name = {"jp": "NotoSansJP.ttf", "mono": "IBMPlexMono.ttf", "sans": "Manrope.ttf"}[kind]
    f = ImageFont.truetype(str(Path(folder) / name), size)
    if hasattr(f, "set_variation_by_axes"):
        try:
            f.set_variation_by_axes(
                [
                    650 if a["minimum"] <= 650 <= a["maximum"] else a["default"]
                    for a in f.get_variation_axes()
                ]
            )
        except OSError:
            pass
    return f


def hits(style: str, side: str):
    if side == "front":
        y = 364 if style in STACKED else 474
        return [dict(action="reveal", x=24, y=y, w=552, h=222 if style in STACKED else 112)]
    if style in STACKED:
        return [
            dict(action=a, rating=r, x=24, y=364 + i * 76, w=552, h=70)
            for i, (a, r) in enumerate([("missed", 1), ("little", 2), ("knew", 3)])
        ]
    return [
        dict(action=a, rating=r, x=20 + i * 188, y=474, w=184, h=112)
        for i, (a, r) in enumerate([("missed", 1), ("little", 2), ("knew", 3)])
    ]


def wrap(text, f, width, japanese=False, *, preserve_compounds=False):
    if japanese and preserve_compounds:
        if "\n" in text:
            return [
                line
                for paragraph in text.split("\n")
                for line in wrap(paragraph, f, width, True, preserve_compounds=True)
            ]
        # Keep kanji compounds plus their following kana together when possible.
        # Oversized runs still split safely below, so arbitrary imports fit.
        tokens = re.findall(
            r"(?:[\u3400-\u9fff々〆ヶ]+[ぁ-ゖー]*|[ァ-ヺー]+|[ぁ-ゖー]+|[A-Za-z0-9]+|.)[、。！？）」』】]*",
            text,
        )
    else:
        tokens = list(text) if japanese else text.split()
    lines = []
    line = ""
    for token in tokens:
        sep = "" if japanese or not line else " "
        if line and f.getlength(line + sep + token) > width:
            lines.append(line)
            line = ""
        if f.getlength(token) > width:
            for c in token:
                if line and f.getlength(line + c) > width:
                    lines.append(line)
                    line = ""
                line += c
        else:
            line += (" " if line and not japanese else "") + token
    if line:
        lines.append(line)
    return lines or [""]


def block(
    draw,
    text,
    box,
    folder,
    kind,
    maximum,
    minimum=18,
    ink=0,
    align="center",
    *,
    preserve_compounds=False,
):
    if not text:
        return
    x, y, w, h = box
    lo, hi = minimum, maximum
    best = None
    while lo <= hi:
        size = (lo + hi) // 2
        f = font(folder, kind, size)
        lines = wrap(text, f, w, kind == "jp", preserve_compounds=preserve_compounds)
        step = round(size * 1.22)
        if step * len(lines) <= h:
            best = (f, lines, step)
            lo = size + 1
        else:
            hi = size - 1
    if best is None:
        raise ValueError(f"Text does not fit {kind} block: {text[:35]}")
    f, lines, step = best
    top = y + (h - step * len(lines)) / 2
    for i, line in enumerate(lines):
        px = x if align == "left" else x + w / 2
        draw.text(
            (px, top + i * step + step / 2),
            line,
            font=f,
            fill=ink,
            anchor="lm" if align == "left" else "mm",
        )


def ellipsis(text, f, width):
    while text and f.getlength(text) > width:
        text = text[:-2].rstrip() + "…"
    return text


def weather(draw, symbol, cx, cy, ink):
    if symbol == "sun":
        draw.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), outline=ink, width=3)
        for i in range(8):
            a = i * math.pi / 4
            draw.line(
                (
                    cx + 17 * math.cos(a),
                    cy + 17 * math.sin(a),
                    cx + 25 * math.cos(a),
                    cy + 25 * math.sin(a),
                ),
                fill=ink,
                width=3,
            )
    elif symbol == "snow":
        for a in [0, math.pi / 3, 2 * math.pi / 3]:
            draw.line(
                (
                    cx - 23 * math.cos(a),
                    cy - 23 * math.sin(a),
                    cx + 23 * math.cos(a),
                    cy + 23 * math.sin(a),
                ),
                fill=ink,
                width=3,
            )
    else:
        draw.line((cx - 24, cy + 9, cx + 24, cy + 9), fill=ink, width=3)
        draw.arc((cx - 29, cy - 10, cx - 1, cy + 16), 150, 280, fill=ink, width=3)
        draw.arc((cx - 15, cy - 23, cx + 17, cy + 10), 170, 350, fill=ink, width=3)
        draw.arc((cx + 7, cy - 10, cx + 31, cy + 15), 260, 360, fill=ink, width=3)
        if symbol == "rain":
            for dx in [-15, 0, 15]:
                draw.line((cx + dx, cy + 17, cx + dx - 4, cy + 27), fill=ink, width=3)
        if symbol == "thunder":
            draw.line(
                (cx + 2, cy + 14, cx - 6, cy + 25, cx + 3, cy + 25, cx - 3, cy + 35),
                fill=ink,
                width=3,
            )


def paper(draw, box):
    x, y, w, h = box
    pts = [(x, y + 3), (x + w // 3, y), (x + w, y + 2), (x + w - 2, y + h - 4)]
    pts += [(x + i, y + h - (i % 11) // 2) for i in range(w, 0, -8)]
    pts += [(x + 2, y + 3)]
    draw.polygon([(a + 2, b + 3) for a, b in pts], fill=210)
    draw.polygon(pts, fill=255)


def avatar(draw, kind, x, y, ink, background, folder):
    if kind == "ascii":
        draw.text((x, y + 20), "(^_^)", font=font(folder, "mono", 22), fill=ink, anchor="mm")
        return
    unit = 5
    if kind == "cat":
        pixels = [
            "1100000011",
            "1110000111",
            "1111111111",
            "1111111111",
            "1101111011",
            "1101111011",
            "1111111111",
            "1110110111",
            "1111001111",
            "0011111100",
        ]
    else:
        pixels = [
            "0001100000",
            "0001100000",
            "1111111111",
            "1000000001",
            "1010010101",
            "1000000001",
            "1010000101",
            "1001111001",
            "1111111111",
            "0010000100",
        ]
    x -= 25
    for row, line in enumerate(pixels):
        for col, v in enumerate(line):
            if v == "1":
                draw.rectangle(
                    (
                        x + col * unit,
                        y + row * unit,
                        x + col * unit + unit - 1,
                        y + row * unit + unit - 1,
                    ),
                    fill=ink,
                )
    if kind == "cat":
        # Eyes and smile are punched out of the solid face.
        for a, b in [(2, 4), (7, 4), (3, 7), (6, 7), (4, 8), (5, 8)]:
            draw.rectangle(
                (x + a * unit, y + b * unit, x + (a + 1) * unit - 1, y + (b + 1) * unit - 1),
                fill=background,
            )


def header(image, context, style, folder, ink, bg):
    d = ImageDraw.Draw(image)
    kind = "mono" if style in MONO else "sans"
    if style in MATERIAL:
        if style == "paperwhite":
            paper(d, (9, 8, 158, 119))
            paper(d, (179, 8, 410, 119))
        else:
            paper(d, (9, 8, 580, 119))
    elif style in {"terminal", "night", "friendly", "pixel"}:
        d.rectangle((10, 10, 589, 589), outline=ink, width=2)
        d.line((12, 128, 588, 128), fill=ink, width=2)
    else:
        d.line((22, 126, 578, 126), fill=ink, width=3 if style in {"board", "large"} else 2)
    d.line((171, 19, 171, 112), fill=ink, width=2)
    w = context.get("weather")
    if w:
        weather(d, w["symbol"], 86, 43, ink)
        block(
            d, f"{round(w['min'])}–{round(w['max'])}°", (18, 77, 139, 38), folder, kind, 30, 22, ink
        )
    else:
        block(d, "···", (18, 45, 139, 50), folder, kind, 30, 22, ink)
    for i, e in enumerate(context.get("events", [])[:3]):
        dt = datetime.fromisoformat(e["start"]).astimezone(ZoneInfo("Europe/Bratislava"))
        same = dt.date().isoformat() == context.get("date")
        clock = dt.strftime("%H:%M" if same else "%a %H:%M")
        yy = 30 + i * 31
        d.text(
            (187, yy),
            ["Next", "Then", "Later"][i],
            font=font(folder, kind, 17),
            fill=ink,
            anchor="lm",
        )
        d.text((244, yy), clock, font=font(folder, kind, 18), fill=ink, anchor="lm")
        tx = 310 if same else 350
        family = "jp" if any(ord(c) > 0x3000 for c in e["title"]) else "sans"
        f = font(folder, family, 21)
        d.text((tx, yy), ellipsis(e["title"], f, 578 - tx), font=f, fill=ink, anchor="lm")
    if context.get("weather_stale") or context.get("calendar_stale"):
        d.arc((562, 108, 575, 121), 35, 315, fill=ink, width=2)
        d.polygon([(575, 107), (575, 113), (570, 107)], fill=ink)


def material_base(style, side, assets):
    src = assets / ("cutout-reveal.png" if side == "front" else "cutout-tiles.png")
    base = Image.open(src).convert("L").resize((600, 600), Image.Resampling.LANCZOS)
    amount = {"paperlight": 0.42, "paperstack": 0.62, "paperwhite": 0.58}[style]
    return Image.blend(base, Image.new("L", (600, 600), 255), amount)


def buttons(image, style, side, folder, ink, bg, assets):
    d = ImageDraw.Draw(image)
    kind = "mono" if style in MONO else "sans"
    material = style in MATERIAL
    if material:
        d.rectangle((0, 467 if style not in STACKED else 365, 600, 600), fill=255)
    for hit in hits(style, side):
        x, y, w, h = [hit[k] for k in ["x", "y", "w", "h"]]
        box = (x + 3, y + 3, x + w - 4, y + h - 4)
        filled = side == "front" or style in {"board", "large"}
        label = {"reveal": "Reveal", "missed": "missed", "little": "knew a little", "knew": "knew"}[
            hit["action"]
        ]
        if style == "large" and hit["action"] == "little":
            label = "knew\na little"
        fill = ink if filled else bg
        text = bg if filled else ink
        if material:
            raw = Image.open(assets / "cutout-tiles.png").convert("L").resize((600, 600))
            tile = raw.crop((35, 468, 205, 580)).resize((w - 6, h - 6), Image.Resampling.LANCZOS)
            mask = tile.point(lambda p: 255 if p < 125 else 0)
            mask = mask.filter(ImageFilter.MedianFilter(3))
            ImageDraw.floodfill(mask, (mask.width // 2, mask.height // 2), 128)
            mask = mask.point(lambda p: 255 if p == 128 else 0)
            if style == "paperwhite":
                pts = [
                    (x + 10, y + 7),
                    (x + w - 18, y + 6),
                    (x + w - 7, y + 18),
                    (x + w - 9, y + h - 15),
                    (x + w - 23, y + h - 7),
                    (x + 17, y + h - 8),
                    (x + 7, y + h - 20),
                    (x + 6, y + 21),
                ]
                d.polygon([(a + 2, b + 2) for a, b in pts], fill=210)
                d.polygon(pts, fill=255, outline=0)
                d.line(pts + [pts[0]], fill=0, width=3)
                text = 0
            else:
                image.paste(tile.point(lambda p: min(75, max(0, p - 20))), (x + 3, y + 3), mask)
                text = 255
            d = ImageDraw.Draw(image)
        elif style == "pixel":
            pts = [
                (x + 9, y + 3),
                (x + w - 10, y + 3),
                (x + w - 10, y + 9),
                (x + w - 4, y + 9),
                (x + w - 4, y + h - 10),
                (x + w - 10, y + h - 10),
                (x + w - 10, y + h - 4),
                (x + 9, y + h - 4),
                (x + 9, y + h - 10),
                (x + 3, y + h - 10),
                (x + 3, y + 9),
                (x + 9, y + 9),
            ]
            d.polygon(pts, fill=fill, outline=ink)
            d.line(pts + [pts[0]], fill=ink, width=3)
        else:
            d.rectangle(box, fill=fill, outline=ink, width=3)
        size = (
            31
            if side == "front"
            else 26
            if style in STACKED or style in MATERIAL
            else 24
            if style == "large"
            else 22
        )
        if "\n" in label:
            lines = label.split("\n")
            f = font(folder, kind, size)
            for j, line in enumerate(lines):
                d.text(
                    (x + w / 2, y + h / 2 + (j - 0.5) * 29), line, font=f, fill=text, anchor="mm"
                )
        else:
            block(d, label, (x + 12, y + 12, w - 24, h - 24), folder, kind, size, 19, text)


def render(style, card, side, context, font_dir, assets, *, text_box=None):
    if style not in IDS:
        raise ValueError("Unknown screen style")
    if style == "washi-wave":
        from .washi_concepts import render_screen

        return render_screen(card, side, context, font_dir=font_dir, assets=assets)
    folder = str(font_dir)
    bg = 0 if style == "night" else 255
    ink = 255 - bg
    image = (
        material_base(style, side, assets) if style in MATERIAL else Image.new("L", (600, 600), bg)
    )
    header(image, context, style, folder, ink, bg)
    d = ImageDraw.Draw(image)
    if style == "buddy":
        d.rectangle((22, 143, 578, 451), outline=ink, width=3)
    if style == "index":
        for yy in [159, 281, 409]:
            d.ellipse((9, yy, 17, yy + 8), outline=ink, width=2)
        d.line((31, 150, 31, 447), fill=ink, width=1)
    if style in {"terminal", "friendly"}:
        d.text((24, 142), "+", font=font(folder, "mono", 24), fill=ink)
        d.text((555, 142), "+", font=font(folder, "mono", 24), fill=ink)
    if style in AVATAR:
        avatar(d, AVATAR[style], 544, 160 if style == "buddy" else 145, ink, bg, folder)
    if card is None:
        if style in MATERIAL:
            d.rectangle((0, 467, 600, 600), fill=255)
        block(
            d,
            "Nothing due.",
            (45, 195, 510, 105),
            folder,
            "mono" if style in MONO else "sans",
            44,
            28,
            ink,
        )
        avatar(d, "ascii" if style in MONO else "cat", 300, 331, ink, bg, folder)
        return image
    top = 128 if style in STACKED else 178 if style in MATERIAL else 145
    bottom = 360 if style in STACKED else 448
    if style == "paperstack":
        paper(d, (22, 132, 556, 228))
        d.ellipse((543, 139, 553, 149), fill=0)
        d.ellipse((546, 141, 549, 144), fill=255)
    left = 43
    right = 520 if style in AVATAR else 557
    width = right - left
    if text_box is not None:
        left, top, width, height = text_box
        bottom = top + height
    align = "left" if style == "board" else "center"
    kind = "mono" if style in MONO else "sans"
    kanji = card.get("kanji", "")
    if side == "front" and not kanji:
        block(
            d,
            card["jp"],
            (left, top, width, bottom - top),
            folder,
            "jp",
            180 if style == "large" else 168,
            30,
            ink,
            align,
            preserve_compounds=text_box is not None,
        )
    else:
        fields = [
            (
                card["jp"],
                "jp",
                (166 if style == "large" else 142)
                if side == "front"
                else 88
                if style == "large"
                else 74,
                22,
            ),
            (kanji, "jp", 62 if side == "front" else 50, 26),
        ] + (
            []
            if side == "front"
            else [
                (card["reading"], kind, 46 if style == "large" else 39, 18),
                (card.get("meaning", ""), "sans", 34 if style == "large" else 29, 18),
            ]
        )
        chosen = None
        for factor in [1 - i * 0.025 for i in range(31)]:
            rows = []
            for text, family, maxsize, minsize in fields:
                if not text:
                    continue
                size = max(minsize, round(maxsize * factor))
                f = font(folder, family, size)
                lines = wrap(
                    text, f, width, family == "jp", preserve_compounds=text_box is not None
                )
                step = round(size * 1.22)
                rows.append((f, lines, step))
            total = sum(len(lines) * step for _, lines, step in rows) + 12 * (len(rows) - 1)
            if total <= bottom - top:
                chosen = (rows, total)
                break
        if chosen is None:
            raise ValueError("Card is too long for this screen")
        rows, total = chosen
        yy = top + (bottom - top - total) / 2
        for f, lines, step in rows:
            for line in lines:
                d.text(
                    (left if align == "left" else left + width / 2, yy + step / 2),
                    line,
                    font=f,
                    fill=ink,
                    anchor="lm" if align == "left" else "mm",
                )
                yy += step
            yy += 12
    buttons(image, style, side, folder, ink, bg, assets)
    return image
