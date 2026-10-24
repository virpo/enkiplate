from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import logging
import hashlib
import recurring_ical_events
from icalendar import Calendar

from .store import Store, now_utc
from .config import HOME_TIMEZONE

BRATISLAVA = ZoneInfo(HOME_TIMEZONE)
LOG = logging.getLogger("enki.context")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def weather_symbol(code: int) -> str:
    if code in (95, 96, 99):
        return "thunder"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if 51 <= code <= 82:
        return "rain"
    return "sun" if code in (0, 1) else "cloud"


def select_events(
    ics: bytes,
    at: datetime,
    excluded: list[str] | None = None,
    labels: dict[str, str] | None = None,
) -> list[dict]:
    """Expand recurrence/overrides, keep real actionable events and retain their source times."""
    calendar = Calendar.from_ical(ics)
    # Floating calendar times use the display's configured home timezone, never the server's timezone.
    events = recurring_ical_events.of(calendar).between(
        at.astimezone(BRATISLAVA) - timedelta(days=1),
        at.astimezone(BRATISLAVA) + timedelta(days=14),
    )
    selected = []
    for event in events:
        identity = str(event.get("UID", ""))
        title = str(event.get("SUMMARY", ""))
        if not title or str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if identity in (excluded or []) or title in (excluded or []):
            continue
        start = event.decoded("DTSTART")
        if not isinstance(start, datetime):
            continue  # all-day background information is not a timed commitment
        if start.tzinfo is None:
            start = start.replace(tzinfo=BRATISLAVA)
        end = event.decoded("DTEND", start)
        if not isinstance(end, datetime):
            end = start
        if end.tzinfo is None:
            end = end.replace(tzinfo=BRATISLAVA)
        if start < at and end <= at:
            continue
        shown = (labels or {}).get(identity, title)
        selected.append(
            {
                "id": identity,
                "title": shown,
                "start": start.astimezone(UTC).isoformat(),
                "end": end.astimezone(UTC).isoformat(),
            }
        )
    selected.sort(key=lambda e: (e["start"], e["id"]))
    return selected[:3]


class ContextService:
    def __init__(self, store: Store):
        self.store = store
        self.errors: dict[str, str] = {}
        self.last_attempt: dict[str, datetime] = {}

    def refresh(self, force: bool = False, at: datetime | None = None) -> dict:
        at = at or now_utc()
        today = at.astimezone(BRATISLAVA).date().isoformat()
        weather = self.store.cached("weather")
        if (
            force
            or not weather
            or datetime.fromisoformat(weather["fetched_at"]) < at - timedelta(minutes=30)
        ):
            if force or self.last_attempt.get("weather", at - timedelta(hours=1)) < at - timedelta(
                minutes=2
            ):
                self.last_attempt["weather"] = at
                try:
                    response = httpx.get(
                        FORECAST_URL,
                        params={
                            "latitude": 48.1486,
                            "longitude": 17.1077,
                            "daily": "temperature_2m_min,temperature_2m_max,weather_code",
                            "timezone": HOME_TIMEZONE,
                            "forecast_days": 1,
                        },
                        timeout=10,
                    )
                    response.raise_for_status()
                    daily = response.json()["daily"]
                    if daily["time"][0] != today:
                        raise ValueError("Forecast is not for today")
                    minimum, maximum = (
                        float(daily["temperature_2m_min"][0]),
                        float(daily["temperature_2m_max"][0]),
                    )
                    if not -60 <= minimum <= maximum <= 60:
                        raise ValueError("Invalid forecast range")
                    self.errors.pop("weather", None)
                    self.store.cache(
                        "weather",
                        {
                            "date": today,
                            "min": minimum,
                            "max": maximum,
                            "symbol": weather_symbol(int(daily["weather_code"][0])),
                        },
                        at,
                    )
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
                    self.errors["weather"] = type(error).__name__
                    LOG.warning(
                        "Weather refresh failed: %s", type(error).__name__
                    )  # snapshot freshness is exposed below, never presented as a successful refresh
        settings = self.store.settings(private=True)
        url = settings["calendar_url"]
        calendar = self.store.cached("calendar")
        feed_hash = hashlib.sha256(url.encode()).hexdigest()
        if calendar and calendar["value"].get("feed_hash") != feed_hash:
            calendar = None
        if url and (
            force
            or not calendar
            or datetime.fromisoformat(calendar["fetched_at"]) < at - timedelta(minutes=10)
        ):
            if force or self.last_attempt.get("calendar", at - timedelta(hours=1)) < at - timedelta(
                minutes=2
            ):
                self.last_attempt["calendar"] = at
                try:
                    with httpx.Client(timeout=12, follow_redirects=False) as client:
                        with client.stream("GET", url) as response:
                            response.raise_for_status()
                            content = bytearray()
                            for chunk in response.iter_bytes():
                                content.extend(chunk)
                                if len(content) > 5_000_000:
                                    raise ValueError("Calendar feed exceeds 5 MB")
                        select_events(bytes(content), at)
                        self.store.cache(
                            "calendar",
                            {"ics": bytes(content).decode("utf-8-sig"), "feed_hash": feed_hash},
                            at,
                        )
                        self.errors.pop("calendar", None)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                    self.errors["calendar"] = type(error).__name__
                    LOG.warning("Calendar refresh failed: %s", type(error).__name__)
        return self.snapshot(at)

    def snapshot(self, at: datetime | None = None) -> dict:
        at = at or now_utc()
        today = at.astimezone(BRATISLAVA).date().isoformat()
        settings = self.store.settings(private=True)
        weather = self.store.cached("weather")
        valid_weather = weather and weather["value"].get("date") == today
        calendar = self.store.cached("calendar") if settings["calendar_url"] else None
        if (
            calendar
            and calendar["value"].get("feed_hash")
            != hashlib.sha256(settings["calendar_url"].encode()).hexdigest()
        ):
            calendar = None
        events = []
        if calendar:
            try:
                events = select_events(
                    calendar["value"]["ics"].encode(),
                    at,
                    settings["calendar_exclude"],
                    settings["calendar_labels"],
                )
            except (ValueError, KeyError, TypeError):
                pass
        tomorrow = (at.astimezone(BRATISLAVA) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        valid_until = int(tomorrow.timestamp())
        for event in events:
            end = datetime.fromisoformat(event["end"])
            start = datetime.fromisoformat(event["start"])
            if end <= start:
                end = start + timedelta(minutes=30)
            valid_until = min(valid_until, int(end.timestamp()))
        return {
            "valid_until_epoch": valid_until,
            "errors": dict(self.errors),
            "date": today,
            "weather": weather["value"] if valid_weather else None,
            "weather_fetched_at": weather["fetched_at"] if valid_weather else None,
            "weather_stale": not valid_weather
            or datetime.fromisoformat(weather["fetched_at"]) < at - timedelta(hours=2),
            "events": events,
            "calendar_configured": bool(settings["calendar_url"]),
            "calendar_fetched_at": calendar["fetched_at"] if calendar else None,
            "calendar_stale": bool(settings["calendar_url"])
            and (
                not calendar
                or datetime.fromisoformat(calendar["fetched_at"]) < at - timedelta(hours=1)
            ),
        }
