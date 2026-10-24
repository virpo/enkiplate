import csv
from pathlib import Path


def test_flash_regions_preserve_factory_settings_and_do_not_overlap():
    source = Path(__file__).resolve().parents[1] / "firmware/Enki/partitions.csv"
    entries = {}
    for row in csv.reader(source.read_text().splitlines()):
        if row and not row[0].startswith("#"):
            entries[row[0]] = (int(row[3], 0), int(row[4], 0))
    assert entries["nvs"] == (0x9000, 0x5000)
    assert entries["app0"][0] == 0x10000
    assert entries["enki_nvs"] == (0x200000, 0x20000)
    regions = sorted(entries.values())
    assert all(a + length <= b for (a, length), (b, _) in zip(regions, regions[1:]))
    assert regions[-1][0] + regions[-1][1] <= 4 * 1024 * 1024


def test_first_install_preserves_settings_and_existing_journal():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "enki_flasher", Path(__file__).resolve().parents[1] / "scripts/flash_device.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = {"type": 1, "subtype": 2, "offset": 0x9000, "size": 0x5000}
    journal = {"type": 1, "subtype": 2, "offset": 0x200000, "size": 0x20000}
    fs = {"type": 1, "subtype": 130, "offset": 0x220000, "size": 0x1E0000}
    target = {"nvs": factory, "enki_nvs": journal, "spiffs": fs}
    assert module.first_install({"nvs": factory}, target)
    assert not module.first_install(target, target)
    import pytest

    with pytest.raises(ValueError):
        module.first_install({"nvs": {**factory, "offset": 0x8000}}, target)
    with pytest.raises(ValueError):
        module.first_install({**target, "enki_nvs": {**journal, "size": 0x10000}}, target)


def test_partition_parser_checks_checksum_and_overlap():
    import importlib.util, hashlib

    spec = importlib.util.spec_from_file_location(
        "enki_flasher", Path(__file__).resolve().parents[1] / "scripts/flash_device.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.ENTRY.pack(0x50AA, 1, 2, 0x9000, 0x5000, b"nvs", 0)
    data = row + b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(row, usedforsecurity=False).digest()
    assert module.partitions(data)["nvs"]["offset"] == 0x9000
    import pytest

    with pytest.raises(ValueError):
        module.partitions(data[:-1] + b"!")
    overlapping = row + module.ENTRY.pack(0x50AA, 1, 2, 0xA000, 0x5000, b"other", 0)
    with pytest.raises(ValueError):
        module.partitions(overlapping)


def test_flash_command_order_and_fail_closed_handoff(tmp_path, monkeypatch):
    import importlib.util, json, subprocess, sys, urllib.error
    from enki_core.config import Config
    import pytest

    spec = importlib.util.spec_from_file_location(
        "flasher", Path(__file__).resolve().parents[1] / "scripts/flash_device.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    build = tmp_path / "build"
    build.mkdir()

    def table(rows):
        raw = b"".join(m.ENTRY.pack(0x50AA, *r, 0) for r in rows)
        import hashlib

        return raw + b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(raw, usedforsecurity=False).digest()

    factory = (1, 2, 0x9000, 0x5000, b"nvs")
    rows = [
        factory,
        (1, 0, 0xE000, 0x2000, b"otadata"),
        (0, 0, 0x10000, 0x1F0000, b"app0"),
        (1, 2, 0x200000, 0x20000, b"enki_nvs"),
        (1, 130, 0x220000, 0x1E0000, b"spiffs"),
    ]
    (build / "Enki.ino.partitions.bin").write_bytes(table(rows))
    for name in ["Enki.ino.bootloader.bin", "boot_app0.bin", "Enki.ino.bin"]:
        (build / name).write_bytes(b"valid-size")
    monkeypatch.setattr(m.Config, "load", lambda: Config(tmp_path, root=tmp_path))
    monkeypatch.setattr(sys, "argv", ["flash", "--port", "/fake/port", "--build", str(build), "--esptool", "/fake/esptool"])
    calls = []
    original = [factory]

    def run(command, **kw):
        args = command[7:]
        calls.append(args)
        if args[0] == "read-flash":
            data = bytearray(b"\xff" * 0x400000)
            raw = table(original)
            data[0x8000 : 0x8000 + len(raw)] = raw
            Path(args[-1]).write_bytes(data)
        return subprocess.CompletedProcess(command, 0, "Detected flash size: 4MB", "")

    monkeypatch.setattr(m.subprocess, "run", run)

    def refused(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))

    monkeypatch.setattr(m.urllib.request, "urlopen", refused)
    m.main()
    assert [c[0] for c in calls] == ["flash-id", "read-flash", "erase-region", "write-flash"]
    assert calls[1][1:3] == ["0", "0x400000"]
    assert calls[2] == ["erase-region", "0x200000", "0x20000"]
    assert calls[3][-8:] == [
        v
        for offset, name in [
            ("0x1000", "Enki.ino.bootloader.bin"),
            ("0x8000", "Enki.ino.partitions.bin"),
            ("0xe000", "boot_app0.bin"),
            ("0x10000", "Enki.ino.bin"),
        ]
        for v in (offset, str(build / name))
    ]
    assert len(list((tmp_path / "hardware").glob("*.bin"))) == 1
    calls.clear()
    original[:] = rows
    m.main()
    assert [c[0] for c in calls] == ["flash-id", "read-flash", "write-flash"]
    calls.clear()
    original[:] = [(1, 2, 0x9000, 0x4000, b"nvs")]
    with pytest.raises(ValueError, match="settings region differs"):
        m.main()
    assert [c[0] for c in calls] == ["flash-id", "read-flash"]
    calls.clear()

    def denied(*args, **kw):
        raise urllib.error.HTTPError("http://localhost", 409, "still closing", {}, None)

    monkeypatch.setattr(m.urllib.request, "urlopen", denied)
    with pytest.raises(SystemExit, match="nothing was written"):
        m.main()
    assert not calls
    (build / "Enki.ino.bin").write_bytes(b"X" * (0x1F0000 + 1))
    with pytest.raises(ValueError, match="does not fit"):
        m.verify_images(build)
