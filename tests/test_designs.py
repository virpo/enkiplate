from enki_core.config import Config
from enki_core.designs import DESIGNS, IDS, hits
from enki_core.render import Renderer
from enki_core.app import create_app
from fastapi.testclient import TestClient

CTX = {"date": "2026-10-24", "weather": {"min": 7, "max": 14, "symbol": "sun"}, "events": []}


def test_all_screens_render_front_back_idle_with_large_separate_targets(tmp_path):
    renderer = Renderer(Config(tmp_path))
    fingerprints = set()
    for style in IDS:
        card = {"id": "long", "jp": "日" * 40, "reading": "a" * 160, "meaning": "word " * 29}
        for side in ["front", "back"]:
            image = renderer.image(card, side, CTX, style)
            assert image.size == (600, 600)
            targets = hits(style, side)
            for h in targets:
                assert h["w"] >= 150 and h["h"] >= 60
                assert (
                    h["x"] >= 0
                    and h["y"] >= 0
                    and h["x"] + h["w"] <= 600
                    and h["y"] + h["h"] <= 600
                )
            for a, b in zip(targets, targets[1:]):
                assert a["x"] + a["w"] <= b["x"] or a["y"] + a["h"] <= b["y"]
        sample = {"id": "word", "jp": "ねこ", "reading": "neko", "meaning": "cat"}
        fingerprints.add(renderer.image(sample, "front", CTX, style).tobytes())
        assert renderer.image(None, "front", CTX, style).size == (600, 600)
    assert len(DESIGNS) == len(fingerprints) == 14


def test_preview_is_read_only_and_theme_choice_reaches_real_card_metadata(tmp_path):
    app = create_app(Config(tmp_path))
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + app.state.store.config.token()
    app.state.context.snapshot = lambda: CTX
    before = app.state.store.stats()
    listing = client.get("/api/designs").json()
    assert len(listing["designs"]) == 14
    for style in ["terminal", "paperwhite"]:
        response = client.get(f"/api/designs/{style}/back.png")
        assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    assert app.state.store.stats() == before
    old = app.state.store.settings()["study_revision"]
    changed = client.patch("/api/settings", json={"display_style": "stack"}).json()
    assert changed["study_revision"] == old + 1
    batch = client.get("/api/study?count=1").json()
    assert batch["display_style"] == "stack" and batch["study_revision"] == old + 1
    assert batch["cards"][0]["back"]["hits"] == hits("stack", "back")
    assert client.patch("/api/settings", json={"display_style": "unknown"}).status_code == 422
