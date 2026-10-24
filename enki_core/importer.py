"""Add verified words or short sentences without replacing existing learning history."""

from __future__ import annotations
import json
from pathlib import Path
from .render import Renderer
from .store import Store


def import_cards(store: Store, path: Path) -> int:
    if path.stat().st_size > 10_000_000:
        raise ValueError("Card import exceeds 10 MB")
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Expected a JSON list of at most 10,000 cards")
    renderer = Renderer(store.config)
    ready = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each card must be an object")
        for key, limit in [("id", 80), ("jp", 40), ("reading", 160), ("meaning", 145)]:
            if not isinstance(row.get(key), str) or not 1 <= len(row[key]) <= limit:
                raise ValueError(f"Each card needs {key}, at most {limit} characters")
        card = {**row, "id": "custom:" + row["id"]}
        for side in ("front", "back"):
            renderer.image(card, side, {"date": "2000-01-01", "weather": None, "events": []})
        ready.append(card)
    with store.connection() as db:
        ordinal = db.execute(
            "SELECT COALESCE(MAX(ordinal),99999) FROM cards WHERE source='personal'"
        ).fetchone()[0]
        for index, card in enumerate(ready):
            db.execute(
                "INSERT INTO cards(id,jp,reading,meaning,kind,stage,source,ordinal) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET jp=excluded.jp,reading=excluded.reading,meaning=excluded.meaning",
                (
                    card["id"],
                    card["jp"],
                    card["reading"],
                    card["meaning"],
                    "custom",
                    4,
                    "personal",
                    ordinal + 1 + index,
                ),
            )
    return len(ready)
