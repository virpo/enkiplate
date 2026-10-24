import hashlib
import json
from datetime import datetime, timedelta, UTC
from unittest.mock import Mock
import pytest
from fsrs import Card, State
from enki_core.config import Config
from enki_core.store import Store
from enki_core.context import ContextService
from enki_core.render import Renderer
from enki_core.device import DeviceBridge

T = datetime(2026, 10, 24, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def immediate_simulated_serial_boot(monkeypatch):
    monkeypatch.setattr("enki_core.device.USB_BOOT_SECONDS", 0)


def test_context_date_staleness_and_calendar_source_isolation(tmp_path):
    s = Store(Config(tmp_path))
    ctx = ContextService(s)
    s.cache("weather", {"date": "2026-10-23", "min": 4, "max": 14, "symbol": "sun"}, T)
    assert ctx.snapshot(T)["weather"] is None
    s.cache(
        "weather",
        {"date": "2026-10-24", "min": 4, "max": 14, "symbol": "sun"},
        T - timedelta(hours=3),
    )
    assert ctx.snapshot(T)["weather_stale"]
    s.update_settings({"calendar_url": "https://example.com/new.ics"})
    s.cache(
        "calendar",
        {
            "ics": "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
            "feed_hash": hashlib.sha256(b"https://example.com/old.ics").hexdigest(),
        },
        T,
    )
    result = ctx.snapshot(T)
    assert result["calendar_stale"] and result["calendar_fetched_at"] is None
    assert result["valid_until_epoch"] == int(datetime(2026, 10, 24, 22, tzinfo=UTC).timestamp())


def test_usb_events_retry_once_and_custom_port(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.send = Mock()
    c = s.next_cards(1)[0]
    e = {
        "id": "usb-review-0001",
        "card_id": c["id"],
        "rating": 3,
        "device_id": "test",
        "reviewed_at": None,
    }
    b.handle({"event": e})
    b.handle({"event": e})
    assert s.stats()["reviews"] == 1
    assert b.send.call_args.args[0]["ids"] == [e["id"]]
    b.identified = True
    b.thread = Mock()
    b.thread.is_alive.return_value = True
    monkeypatch.setattr("enki_core.device.local_address", lambda: "192.168.1.2")
    b.configure("home", "password123", 9999)
    command = b.commands.get_nowait()
    assert command["server"] == "http://192.168.1.2:9999"


def test_idle_polls_and_damaged_cache_recovery(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.batch = Mock()
    b.last_batch = 100
    monkeypatch.setattr("enki_core.device.time.monotonic", lambda: 120)
    b.handle(
        {"status": True, "remaining": 0, "cache_ok": True, "context_epoch": int(T.timestamp())}
    )
    assert not b.batch.called
    monkeypatch.setattr("enki_core.device.time.monotonic", lambda: 161)
    b.handle(
        {"status": True, "remaining": 1, "cache_ok": False, "cards": ["kana:hira:あ"], "back": True}
    )
    b.batch.assert_called_once_with()


def test_automatic_stage_requires_ninety_percent_mature_and_recent_recall(tmp_path):
    s = Store(Config(tmp_path))
    with s.connection() as db:
        cards = list(db.execute("select * from cards where stage=0 order by ordinal"))
        assert len(cards) == 92
        for i, row in enumerate(cards[:82]):
            memory = Card(card_id=row["pk"], state=State.Review, stability=4, difficulty=5, due=T)
            db.execute(
                "update cards set memory=?,due=? where id=?",
                (memory.to_json(), T.isoformat(), row["id"]),
            )
            db.execute(
                "insert into reviews values(?,?,?,?,?,?,?)",
                (f"test:{i}", row["id"], 3, T.isoformat(), T.isoformat(), "test", "unused"),
            )
    s.next_cards(1, at=T)
    assert s.settings()["max_stage"] == 0
    with s.connection() as db:
        row = cards[82]
        m = Card(card_id=row["pk"], state=State.Review, stability=4, difficulty=5, due=T)
        db.execute(
            "update cards set memory=?,due=? where id=?", (m.to_json(), T.isoformat(), row["id"])
        )
    s.next_cards(1, at=T)
    assert s.settings()["max_stage"] == 1


def test_overlapping_events_expire_at_first_visible_event_end(tmp_path):
    s = Store(Config(tmp_path))
    ctx = ContextService(s)
    url = "https://example.com/calendar.ics"
    s.update_settings({"calendar_url": url})
    ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    for uid, start, end in [("long", "070000", "100000"), ("short", "073000", "080000")]:
        ics += f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART:20261024T{start}Z\r\nDTEND:20261024T{end}Z\r\nSUMMARY:{uid}\r\nEND:VEVENT\r\n"
    ics += "END:VCALENDAR\r\n"
    at = datetime(2026, 10, 24, 7, 45, tzinfo=UTC)
    s.cache("calendar", {"ics": ics, "feed_hash": hashlib.sha256(url.encode()).hexdigest()}, at)
    assert ctx.snapshot(at)["valid_until_epoch"] == int(
        datetime(2026, 10, 24, 8, tzinfo=UTC).timestamp()
    )


def test_unknown_answer_is_preserved_and_does_not_block_valid_answers(tmp_path):
    s = Store(Config(tmp_path))
    card = s.next_cards(1)[0]
    unknown = {
        "id": "unknown-review-001",
        "card_id": "custom:missing",
        "rating": 3,
        "device_id": "test",
        "reviewed_at": None,
    }
    assert s.receive_review(unknown)["rejected"]
    assert s.recovery()[0]["event"] == unknown
    assert not s.receive_review({**unknown, "id": "valid-review-001", "card_id": card["id"]}).get(
        "rejected"
    )
    assert s.stats()["reviews"] == 1 and s.stats()["recovery"] == 1


def test_serial_upload_defers_acknowledgements_until_after_raw_bytes(tmp_path):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    card = s.next_cards(1)[0]
    frame = b.renderer.frame(card, "front", {"date": "2026-10-24", "weather": None, "events": []})
    event = {
        "id": "queued-review-001",
        "card_id": card["id"],
        "rating": 3,
        "device_id": "test",
        "reviewed_at": None,
    }
    chunks = []
    b.io = Mock()
    b.io.write.side_effect = lambda data: chunks.append(data)
    b.io.flush.side_effect = AssertionError("Mac CH340 tcdrain can block indefinitely")
    replies = iter([{"event": event}, {"ready": frame["id"]}, {"stored": frame["id"]}])
    b.receive = lambda timeout=1: next(replies)
    b.upload(frame)
    assert json.loads(chunks[0])["cmd"] == "frame"
    assert len(chunks[1]) == 180000
    assert json.loads(chunks[2]) == {"cmd": "ack", "ids": [event["id"]]}
    assert s.stats()["reviews"] == 1


def test_keep_cards_survive_other_cards_becoming_due(tmp_path):
    s = Store(Config(tmp_path))
    cards = s.next_cards(2)
    first, second = cards
    # A context refresh keeps the visible card even when another card has a due review.
    s.review(
        {
            "id": "due-review-001",
            "card_id": second["id"],
            "rating": 1,
            "device_id": "test",
            "reviewed_at": None,
        }
    )
    with s.connection() as db:
        db.execute("update cards set due=? where id=?", ("2000-01-01T00:00:00+00:00", second["id"]))
    assert s.study_cards(2, [first["id"]])[0]["id"] == first["id"]


def test_deadline_refreshes_front_but_preserves_back(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.batch = Mock()
    b.last_batch = 0
    monkeypatch.setattr("enki_core.device.time.time", lambda: 1000)
    monkeypatch.setattr("enki_core.device.time.monotonic", lambda: 200)
    status = {
        "status": True,
        "remaining": 1,
        "cache_ok": True,
        "context_epoch": 950,
        "context_deadline": 990,
        "cards": ["kana:hira:あ"],
    }
    b.handle({**status, "back": True})
    assert not b.batch.called
    b.handle({**status, "back": False})
    b.batch.assert_called_once_with()


def test_batch_freezes_position_before_selection_and_syncs_fresh_clock(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    cards = s.next_cards(2)
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    epoch = [1800000000]
    commands = []
    monkeypatch.setattr("enki_core.device.time.time", lambda: epoch[0])
    # The device revealed the second card after the triggering status, before prepare.
    frozen = {
        "status": True,
        "cards": [cards[1]["id"]],
        "back": True,
        "cache_ok": True,
        "pending": [],
        "frames": [],
    }
    b.send = lambda cmd: commands.append(cmd)

    def response(key, timeout=30, packet=False):
        if key == "status":
            return frozen
        return "ok"

    b.wait_for = response
    b.upload = lambda frame: epoch.__setitem__(0, epoch[0] + 16)
    b.batch()
    assert commands[0] == {"cmd": "prepare"}
    packet = next(c["batch"] for c in commands if c["cmd"] == "batch")
    assert packet["cards"][0]["id"] == cards[1]["id"] and packet["resume_back"]
    assert packet["clock_epoch"] > packet["server_epoch"]
    assert packet["clock_epoch"] == epoch[0]


def test_usb_retries_transfer_failure_and_reidentifies(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.port = "/dev/fake"
    packet = (
        json.dumps({"status": True, "protocol": 1, "device_id": "inkplate-abcd"}).encode() + b"\n"
    )
    devices = []
    writes = []

    def serial_factory(**kwargs):
        device = Mock()
        device.readline.return_value = packet
        device.write.side_effect = lambda chunk: writes.append(json.loads(chunk))
        devices.append(device)
        return device

    monkeypatch.setattr("enki_core.device.serial.Serial", serial_factory)
    b.stop.wait = lambda timeout: False
    calls = [0]

    def handle(reply):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("CRC mismatch")
        b.stop.set()

    b.handle = handle
    b.run()
    assert len(devices) == 2 and calls[0] == 2
    assert [w["cmd"] for w in writes] == ["status", "status"]
    assert all(d.close.called for d in devices)
    assert json.loads(b.pairing_file.read_text())["device_id"] == "inkplate-abcd"


def test_restore_and_disconnect_are_opt_in_and_scrub_configuration(tmp_path):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.start = Mock()
    for value in [
        [],
        {},
        {"enabled": False, "port": "old", "device_id": "inkplate-abcd"},
        {"enabled": True, "port": 5, "device_id": "inkplate-abcd"},
    ]:
        b.pairing_file.write_text(json.dumps(value))
        b.restore()
    b.pairing_file.write_text("not JSON")
    b.restore()
    assert not b.start.called
    b.pairing_file.write_text(
        json.dumps({"enabled": True, "port": "/dev/old", "device_id": "inkplate-abcd"})
    )
    b.restore()
    assert b.resume_after > 0
    b.start.assert_called_once_with("/dev/old", automatic=True, expected_id="inkplate-abcd")
    command = {"cmd": "config", "password": "only-a-test"}
    b.commands.put(command)
    b.message = "Inkplate connected"
    b.disconnect()
    assert b.commands.empty() and command == {}
    assert json.loads(b.pairing_file.read_text())["enabled"] is False
    assert "disconnected" in b.message.lower()


def test_manual_connect_replaces_unidentified_old_port(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))

    class OldWorker:
        alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.alive = False

    old = OldWorker()
    new = Mock()
    b.thread = old
    b.port = "/dev/old"
    b.expected_id = "inkplate-saved"
    monkeypatch.setattr("enki_core.device.ports", lambda: ["/dev/new"])
    monkeypatch.setattr("enki_core.device.threading.Thread", lambda **kw: new)
    b.start()
    assert not old.alive and b.port == "/dev/new" and b.expected_id == "inkplate-saved"
    assert not b.stop.is_set()
    new.start.assert_called_once()


def test_reconnect_releases_prepared_back_without_replacing_it(tmp_path, monkeypatch):
    import time

    s = Store(Config(tmp_path))
    card = s.next_cards(1)[0]
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.port = "/dev/fake"
    b.batch = Mock()
    packet = {
        "status": True,
        "protocol": 1,
        "device_id": "inkplate-abcd",
        "usb_batch": True,
        "cache_ok": True,
        "remaining": 1,
        "back": True,
        "cards": [card["id"]],
        "context_epoch": int(time.time()),
    }
    messages = iter([json.dumps(packet).encode() + b"\n", b'{"aborted":"ok"}\n'])
    writes = []
    device = Mock()

    def read():
        try:
            return next(messages)
        except StopIteration:
            b.stop.set()
            return b""

    device.readline.side_effect = read
    device.write.side_effect = lambda data: writes.append(json.loads(data))
    monkeypatch.setattr("enki_core.device.serial.Serial", lambda **kwargs: device)
    b.run()
    assert [x["cmd"] for x in writes] == ["status", "abort"]
    assert not b.batch.called


def test_queued_configuration_samples_clock_at_send_time(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.port = "/dev/fake"
    epoch = [1800000000]
    b.commands.put({"cmd": "config", "epoch": epoch[0], "password": "test-only"})
    monkeypatch.setattr("enki_core.device.time.time", lambda: epoch[0])
    device = Mock()
    device.readline.return_value = b'{"status":true,"protocol":1,"device_id":"inkplate-abcd"}\n'
    writes = []

    def write(data):
        packet = json.loads(data)
        writes.append(packet)
        if packet["cmd"] == "config":
            b.stop.set()

    device.write.side_effect = write
    monkeypatch.setattr("enki_core.device.serial.Serial", lambda **kwargs: device)
    b.handle = lambda reply: epoch.__setitem__(0, epoch[0] + 64)
    b.run()
    assert writes[-1]["cmd"] == "config" and writes[-1]["epoch"] == 1800000064


def test_wrong_unit_never_receives_queued_credentials(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.port = "/dev/fake"
    b.expected_id = "inkplate-right"
    b.commands.put({"cmd": "config", "password": "test-only"})
    messages = iter(
        [
            b'{"status":true,"protocol":1,"device_id":"inkplate-wrong"}\n',
            b'{"status":true,"device_id":"inkplate-right"}\n',
        ]
    )
    writes = []
    device = Mock()

    def read():
        try:
            return next(messages)
        except StopIteration:
            b.stop.set()
            return b""

    device.readline.side_effect = read
    device.write.side_effect = lambda data: writes.append(json.loads(data))
    monkeypatch.setattr("enki_core.device.serial.Serial", lambda **kwargs: device)
    b.run()
    assert writes == [{"cmd": "status"}] and b.commands.qsize() == 1 and not b.identified
    assert not b.pairing_file.exists()


def test_connect_during_cancellation_starts_one_replacement(tmp_path, monkeypatch):
    import threading

    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    entered = threading.Event()
    release = threading.Event()
    devices = []
    calls = [0]

    def factory(**kwargs):
        device = Mock()
        device.readline.return_value = b'{"status":true,"protocol":1,"device_id":"inkplate-abcd"}\n'
        devices.append(device)
        return device

    monkeypatch.setattr("enki_core.device.serial.Serial", factory)
    monkeypatch.setattr("enki_core.device.ports", lambda: ["/dev/fake"])

    def handle(reply):
        calls[0] += 1
        if calls[0] == 1:
            entered.set()
            release.wait(2)
        else:
            b.stop.set()

    b.handle = handle
    b.start()
    assert entered.wait(2)
    b.disconnect()
    timer = threading.Timer(0.02, release.set)
    timer.start()
    b.start()
    b.thread.join(2)
    timer.join()
    assert len(devices) == 2 and calls[0] == 2 and not b.thread.is_alive()


def test_interrupted_raw_upload_keeps_quiet_interval_across_manual_restart(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    clock = [100.0]
    monkeypatch.setattr("enki_core.device.time.monotonic", lambda: clock[0])
    frame = b.renderer.frames / "partial.raw"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"partial-frame")
    b.io = Mock()
    b.io.write.side_effect = OSError("cancelled mid-frame")
    b.send = Mock()
    b.wait_for = lambda *args: "partial"
    import pytest

    with pytest.raises(OSError):
        b.upload({"id": "partial", "crc32": 1})
    assert b.resume_after == 120
    b.close()
    del b.send  # Use the real sender in the replacement worker.
    del b.wait_for
    writes = []
    device = Mock()
    device.write.side_effect = lambda data: writes.append((clock[0], json.loads(data)))
    device.readline.return_value = b'{"status":true,"protocol":1,"device_id":"inkplate-abcd"}\n'
    monkeypatch.setattr("enki_core.device.serial.Serial", lambda **kw: device)
    monkeypatch.setattr("enki_core.device.ports", lambda: ["/dev/fake"])

    def wait(seconds):
        clock[0] += seconds
        return b.stop.is_set()

    b.stop.wait = wait
    b.handle = lambda reply: b.stop.set()
    b.start()
    b.thread.join(2)
    assert not b.thread.is_alive()
    assert writes == [(120.0, {"cmd": "status"})]
    assert writes[0][0] - 100 > 15  # The firmware's unfinished raw read has expired.


def test_disconnect_waits_for_serial_open_and_sends_nothing_after_cancellation(
    tmp_path, monkeypatch
):
    import threading

    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    opening = threading.Event()
    release = threading.Event()
    device = Mock()

    def open_port():
        opening.set()
        assert release.wait(2)

    device.open.side_effect = open_port
    monkeypatch.setattr("enki_core.device.serial.Serial", lambda **kw: device)
    monkeypatch.setattr("enki_core.device.ports", lambda: ["/dev/fake"])
    b.start()
    assert opening.wait(2)
    timer = threading.Timer(0.03, release.set)
    timer.start()
    b.disconnect()
    timer.join()
    assert not b.thread.is_alive() and not device.write.called
    assert device.close.called and b.expected_id is None


def test_disconnect_never_claims_free_port_if_worker_does_not_exit(tmp_path):
    import pytest

    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.thread = Mock()
    b.thread.is_alive.return_value = True
    with pytest.raises(ValueError, match="still closing"):
        b.disconnect()
    assert "free for flashing" not in b.message


def test_disconnect_clears_identity_set_by_finishing_handshake(tmp_path):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))

    class FinishingWorker:
        alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            b.expected_id = "inkplate-old"  # The reply arrived just as cancellation began.
            self.alive = False

    b.thread = FinishingWorker()
    b.disconnect()
    assert b.expected_id is None


def test_configuration_cannot_survive_concurrent_disconnect(tmp_path, monkeypatch):
    import threading

    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))

    class Worker:
        alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.alive = False

    b.thread = Worker()
    b.identified = True
    validated = threading.Event()
    release = threading.Event()
    disconnected = threading.Event()
    errors = []

    def address():
        validated.set()
        assert release.wait(2)
        return "127.0.0.1"

    monkeypatch.setattr("enki_core.device.local_address", address)

    def configure():
        try:
            b.configure("test-network", "test-password")
        except Exception as e:
            errors.append(e)

    def disconnect():
        b.disconnect()
        disconnected.set()

    config_thread = threading.Thread(target=configure)
    config_thread.start()
    assert validated.wait(2)
    disconnect_thread = threading.Thread(target=disconnect)
    disconnect_thread.start()
    assert not disconnected.wait(0.03)
    release.set()
    config_thread.join(2)
    disconnect_thread.join(2)
    assert not errors and disconnected.is_set() and b.commands.empty()
    assert b.expected_id is None


def test_serial_close_is_serialized_between_disconnect_and_worker(tmp_path):
    import threading

    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    entered = threading.Event()
    release = threading.Event()
    calls = []
    device = Mock()

    def close():
        calls.append("enter")
        entered.set()
        assert release.wait(2)
        calls.append("exit")

    device.close.side_effect = close
    b.io = device
    worker = threading.Thread(target=lambda: b.close_serial(device))
    worker.start()
    assert entered.wait(2)
    disconnect = threading.Thread(target=b.close)
    disconnect.start()
    timer = threading.Timer(0.03, release.set)
    timer.start()
    worker.join(2)
    disconnect.join(2)
    timer.join()
    assert calls == ["enter", "exit", "enter", "exit"]


def test_first_command_waits_for_esp32_boot_after_port_open(tmp_path, monkeypatch):
    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.port = "/dev/fake"
    events = []
    device = Mock()
    device.open.side_effect = lambda: events.append("open")
    device.write.side_effect = lambda data: events.append(("write", json.loads(data)))
    device.readline.return_value = b'{"status":true,"protocol":1,"device_id":"inkplate-abcd"}\n'
    monkeypatch.setattr("enki_core.device.serial.Serial", lambda **kw: device)
    monkeypatch.setattr("enki_core.device.USB_BOOT_SECONDS", 3)

    def wait(seconds):
        events.append(("wait", seconds))
        return b.stop.is_set()

    b.stop.wait = wait
    b.handle = lambda reply: b.stop.set()
    b.run()
    assert events[:3] == ["open", ("wait", 3), ("write", {"cmd": "status"})]


def test_reconnect_refreshes_fresh_front_context_but_keeps_revealed_answer(tmp_path):
    import time

    s = Store(Config(tmp_path))
    b = DeviceBridge(s, ContextService(s), Renderer(s.config))
    b.refresh_on_connect = True
    b.batch = Mock()
    packet = {
        "status": True,
        "remaining": 1,
        "cache_ok": True,
        "context_epoch": int(time.time()),
        "pending": [],
    }
    b.handle({**packet, "back": True})
    b.batch.assert_not_called()
    b.handle({**packet, "back": False})
    b.batch.assert_called_once()
