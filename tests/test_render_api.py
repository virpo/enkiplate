import zlib
from datetime import datetime, UTC
from fastapi.testclient import TestClient
from PIL import Image
from enki_core.config import Config, ROOT
from enki_core.app import create_app
from enki_core.render import Renderer, packed_pixels

CONTEXT = {"date": "2026-10-24", "weather": None, "events": []}


def test_hardware_pixel_nibbles():
    im = Image.new("L", (8, 1))
    im.putdata([0, 36, 73, 109, 146, 182, 219, 255])
    raw = packed_pixels(im)
    assert list(raw) == [0x02, 0x46, 0x8A, 0xCE]
    assert [n >> 1 for b in raw for n in (b >> 4, b & 15)] == list(range(8))


def test_font_and_phrases_fit_and_frames_match(tmp_path):
    renderer = Renderer(Config(tmp_path))
    for jp, reading, meaning in [
        ("ねこ", "neko", "cat"),
        (
            "明日は電車で京都に行きます。",
            "ashita wa densha de kyouto ni ikimasu.",
            "Tomorrow, I will go to Kyoto by train.",
        ),
        (
            "北海道開発庁長官",
            "hokkaidoukaihatsuchouchoukan",
            "Director General of Hokkaido Development Agency",
        ),
    ]:
        card = dict(id="test:" + jp, jp=jp, reading=reading, meaning=meaning)
        for side in ("front", "back"):
            f = renderer.frame(card, side, CONTEXT)
            raw = (renderer.frames / (f["id"] + ".raw")).read_bytes()
            image = Image.open(renderer.frames / (f["id"] + ".png"))
            assert image.size == (600, 600) and len(raw) == 180000
            assert len(set(image.tobytes())) <= 8
            assert packed_pixels(image) == raw
            assert zlib.crc32(raw) & 0xFFFFFFFF == f["crc32"]


def test_api_auth_validation_and_idempotency(tmp_path):
    config = Config(tmp_path)
    app = create_app(config)
    # TestClient is a remote peer. The local browser exception must not bypass auth.
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/status").status_code == 401
        assert client.get("/health").status_code == 200
        assert client.post("/api/login", json=[]).status_code == 400
        assert client.post("/api/login", json={"token": config.token()}).status_code == 204
        assert client.get("/api/status").status_code == 200
        assert (
            client.get("/api/status", headers={"Origin": "https://evil.example"}).status_code == 403
        )
        assert (
            client.patch("/api/settings", json={"calendar_url": "http://example.com"}).status_code
            == 422
        )
        bundle = client.get("/api/study?count=1").json()
        card = bundle["cards"][0]
        assert len(client.get(card["front"]["raw"]).content) == 180000
        event = {
            "id": "test-review-123",
            "card_id": card["id"],
            "rating": 3,
            "device_id": "test",
            "reviewed_at": datetime.now(UTC).isoformat(),
        }
        assert client.post("/api/reviews", json={"events": [event]}).status_code == 200
        assert client.post("/api/reviews", json={"events": [event]}).json()["accepted"][0][
            "duplicate"
        ]
        conflict = client.post("/api/reviews", json={"events": [{**event, "rating": 1}]}).json()
        assert conflict["rejected"][0]["id"] == event["id"]
        assert client.get("/api/recovery").json()[0]["event"]["rating"] == 1
        assert client.get("/api/status").json()["stats"]["reviews"] == 1
        assert client.get("/api/frames/nope.raw").status_code == 404
        assert client.get("/api/backup").content.startswith(b"SQLite format 3")


def test_frame_identity_ignores_fetch_metadata(tmp_path):
    renderer = Renderer(Config(tmp_path))
    card = {"id": "a", "jp": "あ", "reading": "a", "meaning": ""}
    original = renderer.frame(card, "front", CONTEXT)
    changed = renderer.frame(
        card,
        "front",
        {
            **CONTEXT,
            "weather_fetched_at": "different",
            "errors": {"calendar": "test"},
            "valid_until_epoch": 123,
        },
    )
    assert original["id"] == changed["id"]


def test_schema_invalid_review_is_preserved_without_blocking_valid_one(tmp_path):
    config = Config(tmp_path)
    app = create_app(config)
    with TestClient(app, headers={"Authorization": "Bearer " + config.token()}) as client:
        card = client.get("/api/study?count=1").json()["cards"][0]
        bad = {
            "id": "bad-schema-001",
            "card_id": card["id"],
            "rating": 4,
            "device_id": "test",
            "reviewed_at": None,
        }
        good = {**bad, "id": "good-schema-001", "rating": 3}
        result = client.post("/api/reviews", json={"events": [bad, good]}).json()
        assert result["rejected"][0]["id"] == bad["id"]
        assert result["accepted"][0]["id"] == good["id"]
        assert client.get("/api/recovery").json()[0]["event"] == bad


def test_learning_setting_switch_updates_device_revision_and_discards_ineligible_keep(tmp_path):
    app = create_app(Config(tmp_path))
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + app.state.store.config.token()
    app.state.context.snapshot = lambda: CONTEXT
    old = app.state.store.next_cards(2)
    changed = client.patch("/api/settings", json={"start_stage": 2}).json()
    assert changed["start_stage"] == 2 and changed["max_stage"] >= 2
    assert client.get("/api/time").json()["study_revision"] == changed["study_revision"]
    bundle = client.get("/api/study", params=[("count", "2"), ("keep", old[0]["id"])]).json()
    assert bundle["study_revision"] == changed["study_revision"]
    assert len(bundle["cards"]) == 2
    assert all(app.state.store.card(c["id"])["stage"] == 2 for c in bundle["cards"])
