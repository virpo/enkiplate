from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fsrs import Card, Rating, Scheduler, State

from .config import Config
from .content import seed
from .models import Review
from pydantic import ValidationError


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class ReviewConflict(ValueError):
    pass


class Store:
    def __init__(self, config: Config):
        self.config = config
        self.scheduler = Scheduler(desired_retention=config.retention, enable_fuzzing=False)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cards (
                    pk INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                    jp TEXT NOT NULL, reading TEXT NOT NULL, meaning TEXT NOT NULL,
                    kind TEXT NOT NULL, stage INTEGER NOT NULL, source TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, memory TEXT, introduced_at TEXT, due TEXT
                );
                CREATE INDEX IF NOT EXISTS cards_due ON cards(due);
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(id),
                    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 3),
                    reviewed_at TEXT NOT NULL, received_at TEXT NOT NULL,
                    device TEXT NOT NULL, body_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS reviews_card ON reviews(card_id, reviewed_at, id);
                CREATE TABLE IF NOT EXISTS review_recovery (
                    hash TEXT PRIMARY KEY, id TEXT NOT NULL, event TEXT NOT NULL,
                    reason TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cached_context (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at TEXT NOT NULL
                );
            """)
            added_kanji = "kanji" not in {r[1] for r in db.execute("PRAGMA table_info(cards)")}
            upgrade = added_kanji and db.execute("SELECT 1 FROM cards LIMIT 1").fetchone() is not None
            if added_kanji:
                db.execute("ALTER TABLE cards ADD COLUMN kanji TEXT NOT NULL DEFAULT ''")
            seed(db)
            defaults = {
                "max_stage": 0,
                "start_stage": 0,
                "display_style": "washi-wave",
                "study_revision": 0,
                "auto_advance": True,
                "new_per_day": config.new_per_day,
                "calendar_url": "",
                "calendar_exclude": [],
                "calendar_labels": {},
            }
            for key, value in defaults.items():
                db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, json.dumps(value)))
            if upgrade:
                db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='study_revision'")
        self.config.db.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.config.db, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self, private: bool = False) -> dict:
        with self.connection() as db:
            settings = {
                r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")
            }
        if not private:
            settings["calendar_configured"] = bool(settings.pop("calendar_url", ""))
        return settings

    def update_settings(self, values: dict, *, force_refresh: bool = False) -> dict:
        allowed = {
            "max_stage",
            "start_stage",
            "display_style",
            "auto_advance",
            "new_per_day",
            "calendar_url",
            "calendar_exclude",
            "calendar_labels",
        }
        if values.keys() - allowed:
            raise ValueError("Unknown setting")
        values = dict(values)
        if "display_style" in values:
            from .designs import IDS

            if values["display_style"] not in ("cutout", *IDS):
                raise ValueError("Unknown screen style")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = {
                r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")
            }
            if "start_stage" in values:
                values["max_stage"] = max(
                    values["start_stage"], values.get("max_stage", current["max_stage"])
                )
            elif "max_stage" in values and values["max_stage"] < current["start_stage"]:
                values["start_stage"] = values["max_stage"]
            changed = force_refresh or any(
                k in values and values[k] != current[k]
                for k in (
                    "start_stage",
                    "max_stage",
                    "auto_advance",
                    "new_per_day",
                    "display_style",
                )
            )
            for key, value in values.items():
                db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
            if changed:
                db.execute(
                    "UPDATE settings SET value=? WHERE key='study_revision'",
                    (json.dumps(current["study_revision"] + 1),),
                )
            if "calendar_url" in values:
                db.execute("DELETE FROM cached_context WHERE key='calendar'")
        return self.settings()

    def cache(self, key: str, value: dict, at: datetime | None = None):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO cached_context VALUES (?,?,?)",
                (key, json.dumps(value), iso(at or now_utc())),
            )

    def cached(self, key: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM cached_context WHERE key=?", (key,)).fetchone()
            return (
                {"value": json.loads(row["value"]), "fetched_at": row["fetched_at"]}
                if row
                else None
            )

    def card(self, identity: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM cards WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return dict(row)

    def _advance(self, db, settings):
        if not settings["auto_advance"] or settings["max_stage"] >= 4:
            return
        stage = settings["max_stage"]
        rows = list(db.execute("SELECT memory FROM cards WHERE stage=?", (stage,)))
        mature = 0
        for row in rows:
            if row["memory"]:
                memory = Card.from_json(row["memory"])
                if memory.state == State.Review and memory.stability and memory.stability >= 3:
                    mature += 1
        # Stages 0/1 have finite script coverage; vocabulary stages use a bounded proof sample.
        required = max(1, math.ceil(len(rows) * 0.9)) if stage < 2 else min(24, len(rows))
        recent = list(db.execute("SELECT rating FROM reviews ORDER BY reviewed_at DESC LIMIT 60"))
        accuracy = sum(r[0] > 1 for r in recent) / len(recent) if recent else 0
        if mature >= required and accuracy >= 0.85:
            db.execute(
                "UPDATE settings SET value=? WHERE key='max_stage'", (json.dumps(stage + 1),)
            )

    def next_cards(
        self, count: int = 6, exclude: list[str] | None = None, at: datetime | None = None
    ) -> list[dict]:
        at = at or now_utc()
        settings = self.settings(private=True)
        excluded = set(exclude or [])
        midnight = (
            at.astimezone(ZoneInfo(self.config.timezone))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
        )
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._advance(db, settings)
            settings["max_stage"] = json.loads(
                db.execute("SELECT value FROM settings WHERE key='max_stage'").fetchone()[0]
            )
            due = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM cards WHERE memory IS NOT NULL AND due<=? AND stage>=? ORDER BY due, ordinal",
                    (iso(at), settings["start_stage"]),
                )
                if r["id"] not in excluded
            ]
            selected = due[:count]
            reserved = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM cards WHERE memory IS NULL AND introduced_at IS NOT NULL "
                    "AND stage BETWEEN ? AND ? ORDER BY introduced_at,ordinal",
                    (settings["start_stage"], settings["max_stage"]),
                )
                if r["id"] not in excluded
            ]
            selected += reserved[: count - len(selected)]
            introduced = db.execute(
                "SELECT count(*) FROM cards WHERE introduced_at>=?", (iso(midnight),)
            ).fetchone()[0]
            budget = max(0, settings["new_per_day"] - introduced)
            new = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM cards WHERE memory IS NULL AND introduced_at IS NULL AND stage BETWEEN ? AND ? "
                    "ORDER BY stage, CASE WHEN source='personal' THEN 0 ELSE 1 END, ordinal",
                    (settings["start_stage"], settings["max_stage"]),
                )
                if r["id"] not in excluded
            ]
            selected += new[: min(count - len(selected), budget)]
            # Reserving introduction slots makes retries/concurrent devices respect the daily budget.
            for row in selected:
                if row["introduced_at"] is None:
                    db.execute(
                        "UPDATE cards SET introduced_at=? WHERE id=? AND introduced_at IS NULL",
                        (iso(at), row["id"]),
                    )
        return selected

    def review(self, event: dict, at: datetime | None = None) -> dict:
        received = at or now_utc()
        raw_hash = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        effective = (
            datetime.fromisoformat(event["reviewed_at"].replace("Z", "+00:00"))
            if event.get("reviewed_at")
            else received
        )
        if effective.tzinfo is None or effective > received + timedelta(minutes=5):
            raise ValueError("Review time must be timezone-aware and not in the future")
        if effective < received - timedelta(days=730):
            raise ValueError("Review time is too old")
        if event["rating"] not in (1, 2, 3):
            raise ValueError("Rating must be 1, 2 or 3")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM reviews WHERE id=?", (event["id"],)).fetchone()
            if prior:
                if prior["body_hash"] != raw_hash:
                    raise ReviewConflict("The review ID already belongs to a different answer")
                return {"id": event["id"], "duplicate": True}
            row = db.execute("SELECT * FROM cards WHERE id=?", (event["card_id"],)).fetchone()
            if not row:
                raise KeyError(event["card_id"])
            db.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?,?)",
                (
                    event["id"],
                    event["card_id"],
                    event["rating"],
                    iso(effective),
                    iso(received),
                    event["device_id"],
                    raw_hash,
                ),
            )
            logs = list(
                db.execute(
                    "SELECT * FROM reviews WHERE card_id=? ORDER BY reviewed_at,id",
                    (event["card_id"],),
                )
            )
            memory = Card(card_id=row["pk"], due=datetime.fromisoformat(logs[0]["reviewed_at"]))
            # Replay is deterministic and correctly incorporates older offline answers arriving later.
            for log in logs:
                memory, _ = self.scheduler.review_card(
                    memory,
                    Rating(log["rating"]),
                    datetime.fromisoformat(log["reviewed_at"]),
                )
            db.execute(
                "UPDATE cards SET memory=?,due=?,introduced_at=COALESCE(introduced_at,?) WHERE id=?",
                (memory.to_json(), iso(memory.due), iso(effective), event["card_id"]),
            )
        return {"id": event["id"], "duplicate": False, "due": iso(memory.due)}

    def receive_review(self, raw: dict) -> dict:
        try:
            return self.review(Review.model_validate(raw).model_dump())
        except ReviewConflict:
            reason = "Review ID conflicts with a saved answer"
        except KeyError:
            reason = "Card is missing from the learning history"
        except (ValueError, ValidationError):
            reason = "Review fields or timestamp need repair"
        payload = json.dumps(raw, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO review_recovery VALUES(?,?,?,?,?)",
                (digest, str(raw.get("id", "")), payload, reason, iso(now_utc())),
            )
        return {"id": raw.get("id"), "rejected": True, "reason": reason}

    def recovery(self) -> list[dict]:
        with self.connection() as db:
            return [
                {
                    "event": json.loads(r["event"]),
                    "reason": r["reason"],
                    "received_at": r["received_at"],
                }
                for r in db.execute("SELECT * FROM review_recovery ORDER BY received_at")
            ]

    def study_cards(self, count: int, keep: list[str] | None = None) -> list[dict]:
        settings = self.settings()
        cards = []
        for identity in dict.fromkeys(keep or []):
            try:
                card = self.card(identity)
            except KeyError:
                continue
            if (
                card["introduced_at"]
                and card["stage"] >= settings["start_stage"]
                and (card["memory"] or card["stage"] <= settings["max_stage"])
            ):
                cards.append(card)
            if len(cards) == count:
                break
        return (
            cards + self.next_cards(count - len(cards), exclude=[c["id"] for c in cards])
            if len(cards) < count
            else cards
        )

    def stats(self) -> dict:
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM cards").fetchone()[0]
            learned = db.execute("SELECT count(*) FROM cards WHERE memory IS NOT NULL").fetchone()[
                0
            ]
            reviews = db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            recovery = db.execute("SELECT count(*) FROM review_recovery").fetchone()[0]
            sources = [
                dict(r)
                for r in db.execute("SELECT source,count(*) AS cards FROM cards GROUP BY source")
            ]
        return {
            "cards": total,
            "studied": learned,
            "reviews": reviews,
            "recovery": recovery,
            "sources": sources,
        }

    def backup(self, destination: Path):
        with self.connection() as db, sqlite3.connect(destination) as target:
            db.backup(target)
        destination.chmod(0o600)

    def daily_backup(self, at: datetime | None = None):
        day = (at or now_utc()).astimezone(ZoneInfo(self.config.timezone)).date()
        folder = self.config.data / "backups"
        folder.mkdir(mode=0o700, exist_ok=True)
        destination = folder / f"auto-{day.isoformat()}.sqlite3"
        if destination.exists():
            return destination
        with tempfile.NamedTemporaryFile(
            dir=folder, prefix="backup-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
        try:
            self.backup(temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        for old in sorted(folder.glob("auto-????-??-??.sqlite3"))[:-14]:
            old.unlink()
        return destination
