import shutil
import subprocess
import zlib
from datetime import datetime, UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from enki_core.app import create_app
from enki_core.config import Config, ROOT
from enki_core.store import Store
from enki_core.render import Renderer


def test_whole_daily_session_is_downloadable_and_refill_keeps_current_card(tmp_path):
    app = create_app(Config(tmp_path))
    store = app.state.store
    store.update_settings({"start_stage": 2, "display_style": "large"})
    app.state.context.snapshot = lambda: {"date": "2026-10-24", "weather": None, "events": []}
    client = TestClient(app, headers={"Authorization": "Bearer " + store.config.token()})
    first = client.get("/api/study?count=16").json()
    assert len(first["cards"]) == 12
    size = 0
    for card in first["cards"]:
        for side in ("front", "back"):
            f = card[side]
            data = client.get(f["compressed"]).content
            raw = zlib.decompress(data)
            assert len(data) == f["compressed_bytes"]
            assert raw == client.get(f["raw"]).content
            assert len(raw) == 180000 and zlib.crc32(raw) == f["crc32"]
            size += len(data)
    assert size < 350000  # Entire day's 24 sides fit comfortably in device flash.
    assert client.get(first["idle"]["compressed"]).status_code == 200
    for i, card in enumerate(first["cards"][:2]):
        response = client.post(
            "/api/reviews",
            json={
                "events": [
                    {
                        "id": f"offline-session-{i}",
                        "card_id": card["id"],
                        "rating": 3,
                        "device_id": "cache-test",
                        "reviewed_at": datetime.now(UTC).isoformat(),
                    }
                ]
            },
        )
        assert response.json()["accepted"]
    keep = [("keep", c["id"]) for c in first["cards"][2:]]
    second = client.get("/api/study", params=[("count", "16"), *keep]).json()
    assert [c["id"] for c in second["cards"]] == [c["id"] for c in first["cards"][2:]]
    assert store.stats()["reviews"] == 2
    # Restart and content upgrades keep both learning memory and written forms.
    memory = store.card("curated:ねこ")["memory"]
    reloaded = Store(store.config)
    assert reloaded.card("curated:ねこ")["memory"] == memory
    assert reloaded.card("curated:ねこ")["kanji"] == "猫"
    assert reloaded.card("curated:いぬ")["kanji"] == "犬"
    assert reloaded.card("curated:やま")["kanji"] == "山"
    assert reloaded.card("curated:コーヒー")["kanji"] == ""
    assert client.get("/api/study?count=17").status_code == 422


def test_firmware_discards_grades_that_arrive_during_prefetch(tmp_path):
    include = Path.home() / "Documents/Arduino/libraries/ArduinoJson/src"
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler or not (include / "ArduinoJson.h").exists():
        pytest.skip("Native firmware queue check requires the pinned ArduinoJson headers and C++")
    binary = tmp_path / "cache-queue"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-I",
            str(include),
            "-I",
            str(ROOT / "firmware/Enki"),
            str(ROOT / "tests/native/cache_queue.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_kanji_upgrade_preserves_history_and_invalidates_old_device_frames(tmp_path):
    store = Store(Config(tmp_path))
    store.update_settings({"start_stage": 2})
    card = store.next_cards(1)[0]
    store.receive_review(
        {
            "id": "before-content-upgrade",
            "card_id": card["id"],
            "rating": 3,
            "device_id": "migration-test",
            "reviewed_at": None,
        }
    )
    memory = store.card(card["id"])["memory"]
    revision = store.settings()["study_revision"]
    # Recreate the pre-upgrade schema in this isolated fixture database.
    with store.connection() as db:
        db.execute("ALTER TABLE cards DROP COLUMN kanji")
    upgraded = Store(store.config)
    assert upgraded.card(card["id"])["kanji"] == "猫"
    assert upgraded.card(card["id"])["memory"] == memory
    assert upgraded.stats()["reviews"] == 1
    assert upgraded.settings()["study_revision"] == revision + 1
    assert Store(store.config).settings()["study_revision"] == revision + 1


def test_device_decoder_reads_actual_compressed_frames_and_rejects_damage(tmp_path):
    library = ROOT / ".work/inkplate-library/src"
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler or not (library / "graphics/pngle/miniz.c").exists():
        pytest.skip("Native codec check requires the pinned Inkplate library and C++")
    binary = tmp_path / "frame-codec"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-w",
            "-I",
            str(library),
            "-I",
            str(ROOT / "firmware/Enki"),
            str(ROOT / "tests/native/frame_codec.cpp"),
            str(ROOT / "firmware/Enki/FrameCodec.cpp"),
            "-x",
            "c++",
            str(library / "graphics/pngle/miniz.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    renderer = Renderer(Config(tmp_path))
    card = {"id": "codec-test", "jp": "ねこ", "kanji": "猫", "reading": "neko", "meaning": "cat"}
    for style in ("large", "cutout"):
        frame = renderer.frame(card, "back", {"date": "2026-10-24", "events": []}, style)
        stem = renderer.frames / frame["id"]
        subprocess.run(
            [str(binary), str(stem.with_suffix(".z")), str(stem.with_suffix(".raw"))], check=True
        )
