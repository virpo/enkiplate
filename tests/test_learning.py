from datetime import datetime, timedelta, timezone

import pytest

from enki_core.config import Config
from enki_core.store import ReviewConflict, Store

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(Config(tmp_path))


def event(card, rating=3, identity="review_0001", at=T):
    return dict(
        id=identity, card_id=card["id"], rating=rating, reviewed_at=at.isoformat(), device_id="test"
    )


def test_reload_resumes_reservations_and_caps_new(store):
    first = store.next_cards(8, at=T)
    assert [x["id"] for x in first] == [x["id"] for x in store.next_cards(8, at=T)]
    second = store.next_cards(8, exclude=[x["id"] for x in first], at=T)
    assert len(second) == 4
    assert not store.next_cards(8, exclude=[x["id"] for x in first + second], at=T)
    assert (
        len(
            store.next_cards(8, exclude=[x["id"] for x in first + second], at=T + timedelta(days=1))
        )
        == 8
    )


def test_idempotency_and_conflict(store):
    card = store.next_cards(1, at=T)[0]
    e = event(card)
    first = store.review(e, at=T)
    assert not first["duplicate"]
    assert store.review(e, at=T)["duplicate"]
    with pytest.raises(ReviewConflict):
        store.review({**e, "rating": 1}, at=T)
    assert store.stats()["reviews"] == 1


def test_late_offline_reviews_replay_in_order(store, tmp_path):
    other_path = tmp_path / "other"
    other_path.mkdir()
    other = Store(Config(other_path))
    card = store.next_cards(1, at=T)[0]
    a, b = event(card, 1, "review_0001", T), event(card, 3, "review_0002", T + timedelta(days=1))
    for e in [b, a]:
        store.review(e, at=T + timedelta(days=2))
    for e in [a, b]:
        other.review(e, at=T + timedelta(days=2))
    assert store.card(card["id"])["memory"] == other.card(card["id"])["memory"]


def test_retry_without_timestamp_is_stable(store):
    card = store.next_cards(1, at=T)[0]
    e = event(card)
    e["reviewed_at"] = None
    store.review(e, at=T)
    assert store.review(e, at=T + timedelta(days=1))["duplicate"]


def test_bad_times_rejected(store):
    card = store.next_cards(1, at=T)[0]
    with pytest.raises(ValueError):
        store.review(event(card, at=T + timedelta(days=1)), at=T)
    with pytest.raises(ValueError):
        store.review(event(card, at=T.replace(tzinfo=None)), at=T)


def test_backup_is_real_sqlite(store, tmp_path):
    import sqlite3

    target = tmp_path / "backup.sqlite3"
    store.backup(target)
    with sqlite3.connect(target) as db:
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert db.execute("select count(*) from cards").fetchone()[0] > 250


def test_automatic_backups_are_consistent_private_and_bounded(store):
    import sqlite3

    for index in range(15):
        path = store.daily_backup(T + timedelta(days=index))
    assert len(list(path.parent.glob("auto-*.sqlite3"))) == 14
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as db:
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_starting_from_words_skips_reserved_and_due_kana_without_erasing_history(store):
    kana = store.next_cards(4, at=T)
    store.review(event(kana[0]), at=T)
    memory = store.card(kana[0]["id"])["memory"]
    settings = store.update_settings({"start_stage": 2})
    assert settings["max_stage"] >= 2 and settings["study_revision"] == 1
    cards = store.study_cards(2, [c["id"] for c in kana])
    assert len(cards) == 2 and all(c["stage"] == 2 for c in cards)
    assert all(c["stage"] >= 2 for c in store.next_cards(4, at=T + timedelta(days=2)))
    assert store.card(kana[0]["id"])["memory"] == memory and store.stats()["reviews"] == 1


def test_learning_revision_changes_only_for_changed_learning_settings(store):
    assert store.settings()["study_revision"] == 0
    store.update_settings({"calendar_exclude": ["Hidden"]})
    assert store.settings()["study_revision"] == 0
    store.update_settings({"start_stage": 2})
    store.update_settings({"start_stage": 2})
    assert store.settings()["study_revision"] == 1
    store.update_settings({"new_per_day": 15})
    assert store.settings()["study_revision"] == 2
    prior = store.settings()
    store.update_settings({}, force_refresh=True)
    after = store.settings()
    assert after == {**prior, "study_revision": 3}
