import zlib
from PIL import Image, ImageChops
from fastapi.testclient import TestClient

from enki_core.app import create_app
from enki_core.config import Config, ROOT
from enki_core.content import builtin_cards
from enki_core.designs import render, hits, font, wrap
from enki_core.paper_concepts import CARD, CONTEXT
from enki_core.render import Renderer
from enki_core.washi_concepts import TEXT_BOX


def test_japanese_sentences_keep_compounds_on_one_line():
    f = font(str(ROOT / "enki/assets/production"), "jp", 57)
    lines = wrap("明日は電車で京都に行きます。", f, TEXT_BOX[2], True, preserve_compounds=True)
    assert lines == ["明日は電車で", "京都に行きます。"]
    assert all(f.getlength(line) <= TEXT_BOX[2] for line in lines)
    oversized = "日" * 40
    fallback = wrap(oversized, f, TEXT_BOX[2], True, preserve_compounds=True)
    assert "".join(fallback) == oversized and all(
        f.getlength(line) <= TEXT_BOX[2] for line in fallback
    )
    assert wrap("日本語\n京都", f, TEXT_BOX[2], True, preserve_compounds=True) == ["日本語", "京都"]


def test_washi_text_stays_in_the_smaller_box_as_knowledge_grows():
    cards = [c for c in builtin_cards() if c["stage"] >= 2]
    cards.append({"jp": "日" * 40, "reading": "a" * 160, "meaning": "word " * 29})
    x, y, w, h = TEXT_BOX
    material = (
        Image.open(ROOT / "enki/assets/objects/washi/pattern-v3.png")
        .convert("L")
        .resize((600, 600), Image.Resampling.LANCZOS)
    )
    tape = material.point(lambda p: 255 if p < 90 else 0).crop((0, 129, 600, 474))
    assert abs(w / 514 - 0.9) < 0.002 and abs(h / 303 - 0.9) < 0.002
    for card in cards + [None]:
        for side in ("front", "back"):
            image = render(
                "large",
                card,
                side,
                CONTEXT,
                ROOT / "enki/assets/production",
                ROOT / "enki/assets/objects",
                text_box=TEXT_BOX,
            )
            body = ImageChops.invert(image).crop((0, 129, 600, 474))
            assert ImageChops.multiply(body, tape).getbbox() is None
            box = body.getbbox()
            assert box and box[0] >= x and box[2] <= x + w
            assert box[1] + 129 >= y and box[3] + 129 <= y + h


def test_selected_washi_is_a_real_device_theme_and_keeps_large_controls(tmp_path):
    app = create_app(Config(tmp_path))
    client = TestClient(app, headers={"Authorization": "Bearer " + app.state.store.config.token()})
    app.state.context.snapshot = lambda: CONTEXT
    renderer = Renderer(app.state.store.config)
    old = app.state.store.stats()
    assert client.get("/api/designs/washi-wave/back.png").status_code == 200
    assert app.state.store.stats() == old
    response = client.patch("/api/settings", json={"start_stage": 2, "display_style": "washi-wave"})
    assert response.status_code == 200
    batch = client.get("/api/study?count=16").json()
    assert batch["display_style"] == "washi-wave" and len(batch["cards"]) == 12
    total = 0
    for card in batch["cards"]:
        for side in ("front", "back"):
            f = card[side]
            compressed = client.get(f["compressed"]).content
            raw = zlib.decompress(compressed)
            assert len(raw) == 180000 and zlib.crc32(raw) == f["crc32"]
            assert f["hits"] == hits("large", side)
            total += len(compressed)
    # Current queue plus a complete incoming queue, including idle and FS margin.
    assert total * 2 + 100000 < 0x1E0000
    for side in ("front", "back"):
        original = renderer.image(CARD, side, CONTEXT, "large")
        final = renderer.image(CARD, side, CONTEXT, "washi-wave")
        for region in [(0, 0, 600, 128), (0, 474, 600, 600)]:
            assert (
                ImageChops.difference(original.crop(region), final.crop(region)).getbbox() is None
            )
    idle = batch["idle"]
    assert idle["hits"] == []
    assert Image.open(renderer.frames / (idle["id"] + ".png")).size == (600, 600)
