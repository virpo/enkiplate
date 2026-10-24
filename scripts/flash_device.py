"""Verify, back up, and flash the 4 MB Inkplate using separate protected segments."""

from __future__ import annotations
import argparse
import errno
import json
import hashlib
import re
import shutil
import struct
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4
from enki_core.config import Config

ENTRY = struct.Struct("<HBBII16sI")


def partitions(data: bytes) -> dict:
    result = {}
    for offset in range(0, len(data) - 31, 32):
        magic, kind, subtype, start, size, label, flags = ENTRY.unpack_from(data, offset)
        if magic == 0xEBEB:
            if (
                hashlib.md5(data[:offset], usedforsecurity=False).digest()
                != data[offset + 16 : offset + 32]
            ):
                raise ValueError("Partition checksum does not match")
            break
        if magic == 0xFFFF:
            break
        if magic != 0x50AA:
            raise ValueError("Unrecognised partition table")
        name = label.rstrip(b"\0").decode("ascii")
        if name in result or size <= 0:
            raise ValueError("Invalid partition entry")
        result[name] = {
            "type": kind,
            "subtype": subtype,
            "offset": start,
            "size": size,
            "flags": flags,
        }
    if not result:
        raise ValueError("Partition table is empty")
    ranges = sorted((v["offset"], v["offset"] + v["size"]) for v in result.values())
    if (
        any(end > start for (_, end), (start, _) in zip(ranges, ranges[1:]))
        or ranges[-1][1] > 0x400000
    ):
        raise ValueError("Flash regions overlap or exceed 4 MB")
    return result


def verify_images(folder: Path):
    table = partitions((folder / "Enki.ino.partitions.bin").read_bytes())
    if set(table) != {"nvs", "otadata", "app0", "enki_nvs", "spiffs"}:
        raise ValueError("Unexpected partition inventory")
    for name, start, size in [
        ("nvs", 0x9000, 0x5000),
        ("otadata", 0xE000, 0x2000),
        ("app0", 0x10000, 0x1F0000),
        ("enki_nvs", 0x200000, 0x20000),
        ("spiffs", 0x220000, 0x1E0000),
    ]:
        if name not in table or table[name]["offset"] != start or table[name]["size"] != size:
            raise ValueError(f"Unexpected {name} flash region")
    kinds = {
        "nvs": (1, 2),
        "otadata": (1, 0),
        "app0": (0, 0),
        "enki_nvs": (1, 2),
        "spiffs": (1, 130),
    }
    if any(
        (table[n]["type"], table[n]["subtype"]) != kind or table[n].get("flags", 0) != 0
        for n, kind in kinds.items()
    ):
        raise ValueError("Unexpected flash region type or encryption flags")
    segments = [
        (0x1000, "Enki.ino.bootloader.bin", 0x7000),
        (0x8000, "Enki.ino.partitions.bin", 0x1000),
        (0xE000, "boot_app0.bin", 0x2000),
        (0x10000, "Enki.ino.bin", table["app0"]["size"]),
    ]
    for _, name, limit in segments:
        size = (folder / name).stat().st_size
        if not 0 < size <= limit:
            raise ValueError(f"{name} does not fit its flash region")
    return table, segments


def first_install(original: dict, target: dict) -> bool:
    if original.get("nvs") != target["nvs"]:
        raise ValueError(
            "Original settings region differs. A migration is required; nothing was written."
        )
    if "enki_nvs" not in original:
        return True
    if original["enki_nvs"] != target["enki_nvs"] or original.get("spiffs") != target["spiffs"]:
        raise ValueError(
            "Existing Enki storage differs. A migration is required; nothing was written."
        )
    return False


def main():
    config = Config.load()
    root = config.root
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Serial port for the intended Inkplate")
    parser.add_argument("--build", type=Path, default=root / ".work/firmware-build")
    parser.add_argument("--service-url", default="http://127.0.0.1:8787")
    parser.add_argument("--baud", type=int, choices=[115200, 230400, 460800], default=115200)
    parser.add_argument("--esptool", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    table, segments = verify_images(args.build)
    print("Images and protected flash regions verified.", flush=True)
    if args.verify_only:
        return
    if not args.port:
        parser.error("--port is required for flashing; list ports with python -m serial.tools.list_ports")
    tool = args.esptool
    if not tool:
        candidates = [
            Path.home()
            / "Library/Arduino15/packages/soldered-inkplate-boards/tools/esptool_py/5.3.1/esptool",
            root / ".work/bin/esptool",
        ]
        tool = next((p for p in candidates if p.is_file()), None)
    if not tool:
        found = shutil.which("esptool")
        if not found:
            raise SystemExit("Supply --esptool with the pinned esptool executable.")
        tool = Path(found)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                args.service_url.rstrip("/") + "/api/device/disconnect", method="POST"
            ),
            timeout=10,
        ) as response:
            if json.load(response).get("disconnected") is not True:
                raise ValueError("USB release was not confirmed")
    except (OSError, ValueError, urllib.error.URLError) as error:
        reason = getattr(error, "reason", error)
        if (
            not isinstance(reason, ConnectionRefusedError)
            and getattr(reason, "errno", None) != errno.ECONNREFUSED
        ):
            raise SystemExit(
                "Disconnect USB in Enki first. USB release failed; nothing was written."
            ) from error
    command = [str(tool), "--chip", "esp32", "--port", args.port, "--baud", str(args.baud)]

    def run(*arguments):
        completed = subprocess.run(
            command + list(arguments), capture_output=True, text=True, timeout=900
        )
        if completed.returncode:
            raise SystemExit(completed.stdout + completed.stderr)
        return completed.stdout

    print("Checking the powered-on ESP32 and flash size…", flush=True)
    identity = run("flash-id")
    if not re.search(r"Detected flash size:\s*4\s*MB", identity, re.I):
        raise SystemExit("Expected 4 MB flash. Nothing was written.")
    folder = config.data / "hardware"
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = folder / f"original-{stamp}-{uuid4().hex[:6]}.bin"
    temporary = backup.with_suffix(".partial")
    print("Backing up the complete original flash (4 MB)…", flush=True)
    run("read-flash", "0", "0x400000", str(temporary))
    temporary.chmod(0o600)
    data = temporary.read_bytes()
    if len(data) != 0x400000:
        raise SystemExit("Original backup is incomplete. Nothing was written.")
    temporary.replace(backup)
    original = partitions(data[0x8000:0x9000])
    fresh = first_install(original, table)
    print(f"Original backup saved: {backup}", flush=True)
    if fresh:
        print("Initialising only the new Enki journal region…", flush=True)
        run("erase-region", "0x200000", "0x20000")
    print(
        "Writing bootloader, table and app. Factory settings and existing Enki journal are preserved.",
        flush=True,
    )
    arguments = [
        "write-flash",
        "-z",
        "--flash-mode",
        "keep",
        "--flash-freq",
        "keep",
        "--flash-size",
        "keep",
    ]
    for offset, name, _ in segments:
        arguments.extend([hex(offset), str(args.build / name)])
    run(*arguments)
    print(
        "Flash write completed. Connect USB in Enki to verify device status, screen and touch.",
        flush=True,
    )


if __name__ == "__main__":
    main()
