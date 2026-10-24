from __future__ import annotations

import hashlib
import json
import threading
import zlib
from datetime import date, datetime
from zoneinfo import ZoneInfo
from . import designs

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .config import Config

HITS = {
    "front": [{"action": "reveal", "x": 166, "y": 475, "w": 270, "h": 104}],
    "back": [
        {"action": "missed", "rating": 1, "x": 19, "y": 471, "w": 182, "h": 108},
        {"action": "little", "rating": 2, "x": 208, "y": 471, "w": 182, "h": 108},
        {"action": "knew", "rating": 3, "x": 397, "y": 471, "w": 182, "h": 108},
    ],
}


def packed_pixels(image: Image.Image) -> bytes:
    """Inkplate drawBitmap3Bit: two pixels per byte, 0/2/.../14 nibble values."""
    values = image.convert("L").tobytes()
    out = bytearray(len(values) // 2)
    for i in range(0, len(values), 2):
        a, b = (values[i] * 7 + 127) // 255, (values[i + 1] * 7 + 127) // 255
        out[i // 2] = (a << 5) | (b << 1)
    return bytes(out)


class Renderer:
    def __init__(self, config: Config):
        self.config = config
        self.frames = config.data / "frames"
        self.frames.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.font_dir = config.root / "enki" / "assets" / "production"
        self.background = config.root / "enki" / "assets" / "objects" / "cutout-tiles.png"
        if not self.background.exists():
            self.background = config.root / "enki" / "assets" / "objects" / "cutout-desk.png"

    def _asset_signature(self, style="cutout"):
        assets = [
            self.background,
            self.background.with_name("cutout-reveal.png"),
            self.font_dir / "Manrope.ttf",
            self.font_dir / "NotoSansJP.ttf",
            self.font_dir / "IBMPlexMono.ttf",
        ]
        if style == "washi-wave":
            assets.append(self.background.parent / "washi/pattern-v3.png")
        return [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in assets if p.exists()]

    def font(self, size: int, japanese=False):
        name = "NotoSansJP.ttf" if japanese else "Manrope.ttf"
        font = ImageFont.truetype(str(self.font_dir / name), size)
        if hasattr(font, "set_variation_by_axes"):
            axes = font.get_variation_axes()
            font.set_variation_by_axes(
                [600 if a["minimum"] <= 600 <= a["maximum"] else a["default"] for a in axes]
            )
        return font

    def fit(self, text: str, maximum: int, width: int, japanese=False, minimum=16):
        for size in range(maximum, minimum - 1, -1):
            font = self.font(size, japanese)
            if font.getlength(text) <= width:
                return font
        return self.font(minimum, japanese)

    def _text(self, draw, xy, value, size=22, fill=22, anchor=None, width=None, japanese=False):
        font = self.fit(value, size, width, japanese) if width else self.font(size, japanese)
        draw.text(xy, value, font=font, fill=fill, anchor=anchor)

    def _weather(self, draw, symbol: str, x=82, y=42):
        y += {"cloud": 1, "rain": -6, "thunder": -10}.get(symbol, 0)
        ink, width = 24, 3
        if symbol == "sun":
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline=ink, width=width)
            for a, b, c, d in [
                (-22, 0, -16, 0),
                (16, 0, 22, 0),
                (0, -22, 0, -16),
                (0, 16, 0, 22),
                (-16, -16, -12, -12),
                (12, 12, 16, 16),
                (-16, 16, -12, 12),
                (12, -12, 16, -16),
            ]:
                draw.line((x + a, y + b, x + c, y + d), fill=ink, width=width)
        elif symbol == "snow":
            for a, b, c, d in [(0, -21, 0, 21), (-18, -11, 18, 11), (-18, 11, 18, -11)]:
                draw.line((x + a, y + b, x + c, y + d), fill=ink, width=width)
            for a, b, c, d in [
                (-6, -18, 0, -12),
                (6, -18, 0, -12),
                (-6, 18, 0, 12),
                (6, 18, 0, 12),
            ]:
                draw.line((x + a, y + b, x + c, y + d), fill=ink, width=2)
        else:
            draw.arc((x - 20, y - 6, x + 3, y + 13), 80, 270, fill=ink, width=width)
            draw.arc((x - 10, y - 15, x + 14, y + 12), 180, 345, fill=ink, width=width)
            draw.arc((x + 4, y - 5, x + 24, y + 14), 260, 90, fill=ink, width=width)
            draw.line((x - 10, y + 13, x + 14, y + 13), fill=ink, width=width)
            if symbol == "rain":
                for dx in [-11, 1, 13]:
                    draw.line((x + dx, y + 20, x + dx - 3, y + 27), fill=ink, width=3)
            if symbol == "thunder":
                draw.line(
                    (x + 3, y + 15, x - 4, y + 26, x + 5, y + 26, x - 1, y + 36), fill=ink, width=3
                )

    def _context(self, image, context):
        draw = ImageDraw.Draw(image)
        weather = context.get("weather")
        if weather:
            self._weather(draw, weather["symbol"])
            self._text(
                draw, (82, 90), f"{round(weather['min'])}–{round(weather['max'])}°", 31, anchor="mm"
            )
        else:
            self._text(draw, (82, 70), "···", 31, anchor="mm")
        draw.line((177, 21, 177, 118), fill=86, width=1)
        for index, event in enumerate(context.get("events", [])[:3]):
            y = 29 + index * 31
            start = datetime.fromisoformat(event["start"]).astimezone(
                ZoneInfo(self.config.timezone)
            )
            local_date = start.date().isoformat()
            clock = start.strftime("%H:%M")
            if local_date != context["date"]:
                days = (start.date() - date.fromisoformat(context["date"])).days
                clock = start.strftime("%a %H:%M" if days < 7 else "%d/%m %H:%M")
            self._text(draw, (193, y), ["Next", "Then", "Later"][index], 17, fill=24, anchor="lm")
            time_width = 105 if local_date != context["date"] else 64
            self._text(
                draw, (249, y), clock, 20 if time_width > 64 else 23, anchor="lm", width=time_width
            )
            title = event["title"]
            font = self.font(21, japanese=any(ord(c) > 0x3000 for c in title))
            max_width = 574 - (261 + time_width)
            while font.getlength(title) > max_width and len(title) > 1:
                title = title[:-2].rstrip() + "…"
            draw.text((261 + time_width, y), title, font=font, fill=24, anchor="lm")
        # A small honest stale marker, shown only when relevant data is old.
        if context.get("weather_stale") or context.get("calendar_stale"):
            draw.arc((562, 117, 576, 131), 35, 315, fill=70, width=2)
            draw.polygon([(576, 116), (576, 122), (570, 116)], fill=70)

    def _wrapped(self, text, font, width):
        lines = []
        for word in text.split():
            if font.getlength(word) > width:
                chunks, current = [], ""
                for char in word:
                    if current and font.getlength(current + char) > width:
                        chunks.append(current)
                        current = ""
                    current += char
                if current:
                    chunks.append(current)
                for chunk in chunks:
                    if not lines or font.getlength(lines[-1] + " " + chunk) > width:
                        lines.append(chunk)
                    else:
                        lines[-1] += " " + chunk
            elif not lines or font.getlength(lines[-1] + " " + word) > width:
                lines.append(word)
            else:
                lines[-1] += " " + word
        return lines

    def image(
        self, card: dict | None, side: str, context: dict, style: str = "cutout"
    ) -> Image.Image:
        if style != "cutout":
            return designs.render(style, card, side, context, self.font_dir, self.background.parent)
        background = self.background
        if card is None:
            background = background.with_name("cutout-desk.png")
        elif side == "front":
            background = background.with_name("cutout-reveal.png")
        image = Image.open(background).convert("L").resize((600, 600), Image.Resampling.LANCZOS)
        image = image.filter(ImageFilter.GaussianBlur(0.45)).point(
            lambda p: min(255, max(0, round(p * 1.1 - 2)))
        )
        self._context(image, context)
        ink = Image.new("RGBA", (440, 246))
        draw = ImageDraw.Draw(ink)
        if card is None:
            self._text(draw, (220, 116), "Nothing due.", 35, fill=(24, 24, 24, 255), anchor="mm")
        elif side == "front":
            if card.get("kanji"):
                self._text(
                    draw,
                    (220, 83),
                    card["jp"],
                    132,
                    fill=(20, 20, 20, 255),
                    anchor="mm",
                    width=404,
                    japanese=True,
                )
                self._text(
                    draw,
                    (220, 194),
                    card["kanji"],
                    52,
                    fill=(20, 20, 20, 255),
                    anchor="mm",
                    width=404,
                    japanese=True,
                )
            elif len(card["jp"]) <= 10:
                self._text(
                    draw,
                    (220, 116),
                    card["jp"],
                    174,
                    fill=(20, 20, 20, 255),
                    anchor="mm",
                    width=404,
                    japanese=True,
                )
            else:
                for size in range(70, 25, -1):
                    font = self.font(size, True)
                    lines = self._wrapped(card["jp"], font, 400)
                    if len(lines) * (size + 8) <= 220:
                        break
                y = (246 - len(lines) * (size + 8)) / 2
                for value in lines:
                    draw.text((220, y), value, font=font, fill=(20, 20, 20, 255), anchor="mt")
                    y += size + 8
        else:
            long = len(card["jp"]) > 10
            for reduction in range(16):
                jp_font = (
                    self.fit(card["jp"], max(26, (36 if long else 84) - reduction), 404, True)
                    if not long
                    else self.font(max(26, 36 - reduction), True)
                )
                reading_font = self.font(max(18, (26 if long else 41) - reduction))
                meaning_font = self.font(max(18, 29 - reduction))
                kanji_font = self.font(max(26, 42 - reduction), True)
                jp_lines = self._wrapped(card["jp"], jp_font, 400)
                reading_lines = self._wrapped(card["reading"], reading_font, 400)
                meaning_lines = self._wrapped(card["meaning"], meaning_font, 400)
                rows = (
                    [(v, jp_font) for v in jp_lines]
                    + [
                        (v, kanji_font)
                        for v in self._wrapped(card.get("kanji", ""), kanji_font, 400)
                    ]
                    + [(v, reading_font) for v in reading_lines]
                    + [(v, meaning_font) for v in meaning_lines]
                )
                height = sum(f.size + 7 for _, f in rows)
                if height <= 224:
                    break
            if height > 224:
                raise ValueError("Card exceeds readable paper capacity")
            y = (246 - height) / 2
            for value, font in rows:
                draw.text((220, y), value, font=font, fill=(20, 20, 20, 255), anchor="mt")
                y += font.size + 7
        image = image.convert("RGBA")
        image.alpha_composite(ink.rotate(1, resample=Image.Resampling.BICUBIC), (81, 178))
        draw = ImageDraw.Draw(image)
        if card and side == "back":
            for index, label in enumerate(["missed", "knew a little", "knew"]):
                self._text(
                    draw,
                    (111 + index * 189, 522),
                    label,
                    23,
                    fill=(248, 248, 248, 255),
                    anchor="mm",
                    width=154,
                )
        elif card:
            self._text(draw, (300, 522), "Reveal", 25, fill=(248, 248, 248, 255), anchor="mm")
        return image.convert("L")

    def frame(self, card: dict | None, side: str, context: dict, style: str = "cutout") -> dict:
        key = hashlib.sha256(
            json.dumps(
                {
                    "card": card
                    and {k: card.get(k, "") for k in ("id", "jp", "reading", "meaning", "kanji")},
                    "side": side,
                    "context": {
                        k: context.get(k)
                        for k in ("date", "weather", "events", "weather_stale", "calendar_stale")
                    },
                    "renderer": 18 if style == "washi-wave" else 15,
                    "style": style,
                    "assets": self._asset_signature(style),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        png, raw = self.frames / f"{key}.png", self.frames / f"{key}.raw"
        with self.lock:
            if not png.exists() or not raw.exists() or raw.stat().st_size != 180000:
                image = self.image(card, side, context, style)
                palette = Image.new("P", (1, 1))
                tones = [round(i * 255 / 7) for i in range(8)]
                palette.putpalette(
                    [c for tone in tones for c in (tone, tone, tone)] + [255] * (768 - 24)
                )
                image = (
                    image.convert("RGB")
                    .quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
                    .convert("L")
                )
                data = packed_pixels(image)
                raw_temp = raw.with_suffix(".raw.tmp")
                raw_temp.write_bytes(data)
                raw_temp.replace(raw)
                levels = image
                png_temp = png.with_suffix(".png.tmp")
                levels.save(png_temp, format="PNG")
                png_temp.replace(png)
                # Bound disk use. Devices retain their own cached frames.
                stale = sorted(self.frames.glob("*.raw"), key=lambda p: p.stat().st_mtime)
                for old in stale[:-256]:
                    if old != raw:
                        old.unlink(missing_ok=True)
                        old.with_suffix(".png").unlink(missing_ok=True)
                        old.with_suffix(".z").unlink(missing_ok=True)
            data = raw.read_bytes()
            compressed = raw.with_suffix(".z")
            if not compressed.exists():
                temporary = compressed.with_suffix(".z.tmp")
                temporary.write_bytes(zlib.compress(data, level=9))
                temporary.replace(compressed)
        return {
            "id": key,
            "png": f"/api/frames/{key}.png",
            "raw": f"/api/frames/{key}.raw",
            "bytes": len(data),
            "compressed": f"/api/frames/{key}.z",
            "compressed_bytes": compressed.stat().st_size,
            "crc32": zlib.crc32(data) & 0xFFFFFFFF,
            "hits": (HITS[side] if style == "cutout" else designs.hits(style, side))
            if card
            else [],
        }
