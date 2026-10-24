from __future__ import annotations

import os
import fcntl
import secrets
from dataclasses import dataclass
from pathlib import Path

HOME_TIMEZONE = "Europe/Bratislava"
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    data: Path
    root: Path = ROOT
    new_per_day: int = 12
    retention: float = 0.9

    @property
    def timezone(self):
        return HOME_TIMEZONE

    @classmethod
    def load(cls) -> Config:
        data = Path(os.environ.get("ENKI_DATA_DIR", ROOT / "data")).expanduser().resolve()
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        return cls(data=data)

    @property
    def db(self) -> Path:
        return self.data / "enki.sqlite3"

    def token(self) -> str:
        path = self.data / "device-token"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            value = stream.read().strip()
            if len(value) < 32:
                value = secrets.token_urlsafe(32)
                stream.seek(0)
                stream.truncate()
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            return value
