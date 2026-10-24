from datetime import datetime, timezone
from enki_core.context import select_events, weather_symbol


def calendar(*events):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        + "".join("BEGIN:VEVENT\r\n" + e + "\r\nEND:VEVENT\r\n" for e in events)
        + "END:VCALENDAR\r\n"
    ).encode()


def test_event_triage_and_recurrence():
    data = calendar(
        "UID:repeat\r\nDTSTART;TZID=Europe/Bratislava:20261022T160000\r\nDTEND;TZID=Europe/Bratislava:20261022T170000\r\nRRULE:FREQ=DAILY;COUNT=5\r\nSUMMARY:Coffee break",
        "UID:allday\r\nDTSTART;VALUE=DATE:20261023\r\nSUMMARY:Background",
        "UID:cancel\r\nDTSTART:20261023T170000Z\r\nSTATUS:CANCELLED\r\nSUMMARY:Cancelled",
        "UID:float\r\nDTSTART:20261023T180000\r\nSUMMARY:Japanese",
    )
    at = datetime(2026, 10, 23, 14, 30, tzinfo=timezone.utc)
    events = select_events(data, at)
    assert [e["title"] for e in events] == ["Coffee break", "Japanese", "Coffee break"]
    assert events[1]["start"] == "2026-10-23T16:00:00+00:00"
    assert select_events(data, at, ["repeat"])[0]["title"] == "Japanese"


def test_dst_calendar_keeps_local_time():
    data = calendar(
        "UID:daily\r\nDTSTART;TZID=Europe/Bratislava:20261024T160000\r\nRRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Walk"
    )
    events = select_events(data, datetime(2026, 10, 24, 0, tzinfo=timezone.utc))
    assert [e["start"][11:16] for e in events] == ["14:00", "15:00", "15:00"]


def test_weather_symbols():
    assert [weather_symbol(x) for x in (0, 3, 63, 95, 73)] == [
        "sun",
        "cloud",
        "rain",
        "thunder",
        "snow",
    ]


def test_calendar_title_override():
    data = calendar("UID:pickup\r\nDTSTART:20261024T140000Z\r\nSUMMARY:A very long event title")
    events = select_events(
        data, datetime(2026, 10, 24, 10, tzinfo=timezone.utc), labels={"pickup": "Break"}
    )
    assert events[0]["title"] == "Break"
