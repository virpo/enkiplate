"""Install the local Mac host as a user LaunchAgent. No administrator privileges."""

import json
import os
import plistlib
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from enki_core.config import Config


def install():
    root = Path(__file__).resolve().parents[1]
    config = Config.load()
    label = "io.virpo.enki"
    folder = Path.home() / "Library/LaunchAgents"
    folder.mkdir(parents=True, exist_ok=True)
    logs = config.data / "logs"
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("Install uv first.")
    plist = folder / f"{label}.plist"
    value = {
        "Label": label,
        "ProgramArguments": [
            str(Path(uv).resolve()),
            "run",
            "--frozen",
            "enki",
            "serve",
            "--host",
            "0.0.0.0",
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
            "ENKI_DATA_DIR": str(config.data),
        },
        "StandardOutPath": str(logs / "service-out.log"),
        "StandardErrorPath": str(logs / "service-error.log"),
    }
    with plist.open("wb") as stream:
        plistlib.dump(value, stream)
    plist.chmod(0o600)
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    if subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0:
        subprocess.run(["launchctl", "bootout", target], check=True)
    # launchd tears down a booted-out job asynchronously. Do not report success until the replacement serves health.
    deadline = time.monotonic() + 30
    while True:
        result = subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True
        )
        if result.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise SystemExit("Could not start Enki: " + result.stderr.strip())
        time.sleep(0.25)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8787/health", timeout=1) as response:
                if json.load(response).get("ok"):
                    print("🪨 enki starts at login: http://localhost:8787")
                    print(f"Log: {logs / 'enki.log'}")
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.25)
    subprocess.run(["launchctl", "bootout", target], capture_output=True)
    raise SystemExit(f"Enki did not become ready. Read {logs / 'enki.log'}.")


if __name__ == "__main__":
    install()
