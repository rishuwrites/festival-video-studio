"""Build the 2026 long-form publishing calendar from owner-verified source data."""

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_DIR = ROOT / "calendar"
SLOTS_PATH = ROOT / "config" / "slots.json"
TOPIC_POOL_PATH = CALENDAR_DIR / "topic_pool.json"
FESTIVAL_DATES_PATH = ROOT / "data" / "festival_dates_2026.json"
PANCHANG_PATH = ROOT / "data" / "panchang_2026_11_18_to_12_31.csv"
OUTPUT_JSON = CALENDAR_DIR / "content_calendar.json"
CALENDAR_FIELDS = [
    "date", "slot", "publish_time_ist", "type", "topic_hi", "topic_en",
    "festival_date", "festival_tradition", "thumbnail_text_hi", "thumbnail_color",
    "thumbnail_symbol", "status", "youtube_video_id", "drive_link", "notes",
]
ALLOWED_STATUSES = {
    "planned", "generated", "scheduled", "uploaded",
    "failed_saved_to_drive", "skipped", "blocked_unverified",
}
PANCHARANG_REQUIRED = (
    "tithi", "paksha", "nakshatra", "moon_rashi", "rahu_kaal_start",
    "rahu_kaal_end", "sunrise",
)
RASHIS = (
    ("मेष", "Aries", "#D94B45", "♈"),
    ("वृषभ", "Taurus", "#467A54", "♉"),
    ("मिथुन", "Gemini", "#4F7DB8", "♊"),
    ("कर्क", "Cancer", "#587AA3", "♋"),
    ("सिंह", "Leo", "#D18A2B", "♌"),
    ("कन्या", "Virgo", "#658A5B", "♍"),
    ("तुला", "Libra", "#A45B9A", "♎"),
    ("वृश्चिक", "Scorpio", "#8A3C47", "♏"),
    ("धनु", "Sagittarius", "#8067AE", "♐"),
    ("मकर", "Capricorn", "#526875", "♑"),
    ("कुंभ", "Aquarius", "#3B8A96", "♒"),
    ("मीन", "Pisces", "#4F71A7", "♓"),
)


class CalendarBuildError(ValueError):
    pass


def prepublish_date(festival_date, calendar_start, lead_days=None):
    """Return the chosen publish date and whether it is late for the configured window."""
    if lead_days is None:
        try:
            minimum = int(os.getenv("PRE_PUBLISH_DAYS_MIN", "2"))
            maximum = int(os.getenv("PRE_PUBLISH_DAYS_MAX", "3"))
        except ValueError as exc:
            raise ValueError("PRE_PUBLISH_DAYS_MIN/MAX must be integers") from exc
        if minimum < 2 or maximum > 3 or minimum > maximum:
            raise ValueError("PRE_PUBLISH_DAYS_MIN/MAX must be an ordered subset of 2 to 3")
        lead_days = minimum
    if lead_days not in (2, 3):
        raise ValueError("Festival videos must publish 2 or 3 days before the observance")
    target = dt.date.fromisoformat(festival_date)
    start = dt.date.fromisoformat(calendar_start)
    if target < start:
        raise ValueError("Cannot pre-publish a festival dated before the calendar start")
    scheduled = target - dt.timedelta(days=lead_days)
    if scheduled < start:
        return start.isoformat(), True
    return scheduled.isoformat(), False


def _read_panchang(path, start, end):
    rows = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            date = (row.get("date") or "").strip()
            if date:
                if date in rows:
                    raise CalendarBuildError(f"Duplicate panchang row for {date}")
                rows[date] = {key: (value or "").strip() for key, value in row.items()}
    missing = []
    invalid = []
    day = start
    while day <= end:
        iso_date = day.isoformat()
        row = rows.get(iso_date)
        if not row:
            missing.append(iso_date)
        else:
            blanks = [field for field in PANCHARANG_REQUIRED if not row.get(field)]
            if blanks:
                invalid.append(f"{iso_date}: missing {', '.join(blanks)}")
        day += dt.timedelta(days=1)
    if missing or invalid:
        details = []
        if missing:
            details.append("missing dates: " + ", ".join(missing))
        if invalid:
            details.append("incomplete rows: " + "; ".join(invalid))
        raise CalendarBuildError("Panchang data is incomplete (" + " | ".join(details) + ")")
    return rows


def _read_festivals(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    events = payload.get("entries")
    if not isinstance(events, list):
        raise CalendarBuildError("festival_dates_2026.json must contain an entries list")
    unverified = []
    valid = []
    for event in events:
        if not isinstance(event, dict):
            raise CalendarBuildError("Every festival-date entry must be an object")
        for field in (
            "name_hi", "name_en", "date", "tithi_note", "verified",
            "source_urls", "notes", "tradition",
        ):
            if field not in event:
                raise CalendarBuildError(f"Festival-date entry is missing {field}")
        if not isinstance(event["verified"], bool):
            raise CalendarBuildError(f"Festival {event['name_en']} must use a boolean verified value")
        source_urls = event["source_urls"]
        if (
            not isinstance(source_urls, list)
            or any(not isinstance(url, str) or not url.startswith("https://") for url in source_urls)
            or len(set(source_urls)) != len(source_urls)
        ):
            raise CalendarBuildError(
                f"Festival {event['name_en']} must have a list of unique HTTPS source URLs"
            )
        if not isinstance(event["notes"], str) or not isinstance(event["tradition"], str):
            raise CalendarBuildError(
                f"Festival {event['name_en']} notes and tradition must be strings"
            )
        date = str(event["date"] or "").strip()
        if date:
            try:
                dt.date.fromisoformat(date)
            except ValueError as exc:
                raise CalendarBuildError(f"Invalid date for {event['name_en']}: {date!r}") from exc
        if not event["verified"]:
            unverified.append(
                f"- {event['name_en']} ({date or 'date unresolved'}): "
                f"{event['notes'] or event['tithi_note'] or 'date needs verification'}"
            )
            continue
        if not date:
            raise CalendarBuildError(f"Verified festival {event['name_en']} has no date")
        if len(source_urls) < 2:
            raise CalendarBuildError(
                f"Verified festival {event['name_en']} needs at least two HTTPS sources"
            )
        if len({urlparse(url).netloc for url in source_urls}) < 2:
            raise CalendarBuildError(
                f"Verified festival {event['name_en']} needs independent source hosts"
            )
        valid.append(event)
    return valid, unverified


def _read_topic_pool(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise CalendarBuildError("topic_pool.json must contain a topics list")
    if len(topics) < 300:
        raise CalendarBuildError(f"topic_pool.json needs at least 300 topics; found {len(topics)}")
    required = ("type", "evergreen", "earliest_date", "latest_date")
    for item in topics:
        if not isinstance(item, dict) or any(field not in item for field in required):
            raise CalendarBuildError("Every topic needs type, evergreen, earliest_date, and latest_date")
        if not isinstance(item.get("topic_hi"), str) or not item["topic_hi"].strip():
            raise CalendarBuildError("Every topic-pool entry needs a Hindi title")
        if not isinstance(item.get("topic_en"), str) or not item["topic_en"].strip():
            raise CalendarBuildError("Every topic-pool entry needs an English title")
        if not isinstance(item["evergreen"], bool):
            raise CalendarBuildError("Topic evergreen values must be booleans")
    titles = [
        (item["topic_hi"].strip().casefold(), item["topic_en"].strip().casefold())
        for item in topics
    ]
    if len(set(titles)) != len(titles):
        raise CalendarBuildError("topic_pool.json contains duplicate titles")
    return topics


def _previous_rows(path):
    if not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        (row["date"], int(row["slot"])): row
        for row in payload.get("videos", [])
        if row.get("status") in ALLOWED_STATUSES
    }


def _topic_for(topics, topic_type, used, publish_date):
    for topic in topics:
        if topic.get("type") == topic_type and topic.get("evergreen") is True:
            key = topic["topic_hi"].casefold()
            if (
                key not in used
                and topic.get("earliest_date", "") <= publish_date
                <= topic.get("latest_date", "9999-12-31")
            ):
                used.add(key)
                return topic
    raise CalendarBuildError(f"No unused evergreen topics remain for type {topic_type}")


def _verified_events_for(events, publish_date, min_days, max_days, calendar_start):
    publish_day = dt.date.fromisoformat(publish_date)
    start_day = dt.date.fromisoformat(calendar_start)
    return [
        event for event in events
        if (
            min_days <= (dt.date.fromisoformat(event["date"]) - publish_day).days <= max_days
            or (
                publish_day == start_day
                and dt.date.fromisoformat(event["date"]) >= start_day
                and dt.date.fromisoformat(event["date"])
                <= start_day + dt.timedelta(days=min_days - 1)
            )
        )
    ]


def _event_topic(topics, event, topic_type, used, publish_date):
    keys = {event["name_en"].casefold(), event["name_hi"].casefold()}
    for topic in topics:
        if topic.get("type") != topic_type:
            continue
        if str(topic.get("festival_key", "")).casefold() not in keys:
            continue
        if not topic.get("earliest_date", "") <= publish_date <= topic.get("latest_date", "9999-12-31"):
            continue
        title = topic["topic_hi"].casefold()
        if title not in used:
            used.add(title)
            return topic
    return None


def _rashi_topic(topics, rashi_index, topic_type, used, episode=None):
    sign_hi, sign_en, color, symbol = RASHIS[rashi_index % len(RASHIS)]
    candidates = [
        item for item in topics
        if item.get("type") == topic_type
        and item.get("rashi_index") == rashi_index % len(RASHIS)
        and (episode is None or item.get("episode") == episode)
    ]
    for topic in candidates:
        key = topic["topic_hi"].casefold()
        if key not in used:
            used.add(key)
            return topic, sign_hi, sign_en, color, symbol
    raise CalendarBuildError(f"No unused {topic_type} topic for {sign_en}")


def _thumbnail_text(topic):
    words = topic.split()
    text = " ".join(words[:4])
    return text if len(text.split()) >= 2 else f"{text} विशेष"


def build_rows(start_date, end_date, slots_path=SLOTS_PATH, topic_pool_path=TOPIC_POOL_PATH,
               festivals_path=FESTIVAL_DATES_PATH, panchang_path=PANCHANG_PATH,
               previous_path=OUTPUT_JSON):
    try:
        start = dt.date.fromisoformat(start_date)
        end = dt.date.fromisoformat(end_date)
    except ValueError as exc:
        raise CalendarBuildError("Calendar dates must use YYYY-MM-DD") from exc
    if start > end:
        raise CalendarBuildError("Calendar start date must not be after end date")

    slots_payload = json.loads(Path(slots_path).read_text(encoding="utf-8"))
    slots = slots_payload.get("slots", [])
    if len(slots) != 10 or [slot.get("slot") for slot in slots] != list(range(1, 11)):
        raise CalendarBuildError("config/slots.json must define exactly slots 1 through 10 in order")
    if any(slot.get("format", "long") != "long" for slot in slots):
        raise CalendarBuildError("All daily slots must remain long-form")

    festivals, unverified = _read_festivals(festivals_path)
    if unverified:
        print("Festival/vrat dates still requiring owner verification:")
        print("\n".join(unverified))
    panchang = _read_panchang(panchang_path, start, end)
    topics = _read_topic_pool(topic_pool_path)
    previous = _previous_rows(previous_path)
    used = set()
    rows = []
    day = start
    rashi_index = 0
    lead_min = int(os.getenv("PRE_PUBLISH_DAYS_MIN", "2"))
    lead_max = int(os.getenv("PRE_PUBLISH_DAYS_MAX", "3"))
    if lead_min < 2 or lead_max > 3 or lead_min > lead_max:
        raise CalendarBuildError("PRE_PUBLISH_DAYS_MIN/MAX must be an ordered subset of 2 to 3")

    while day <= end:
        iso_date = day.isoformat()
        day_rows = []
        event_candidates = _verified_events_for(
            festivals, iso_date, lead_min, lead_max, start.isoformat(),
        )
        for slot in slots:
            slot_no = int(slot["slot"])
            slot_type = slot["type"]
            festival_date = ""
            festival_tradition = ""
            note = ""
            status = "planned"
            row_type = slot_type
            color, symbol = "#8B6B9E", "✦"
            if slot_type == "daily_panchang_rashifal":
                record = panchang[iso_date]
                topic_hi = f"आज का पंचांग और बारह राशियाँ: {iso_date}"
                topic_en = f"Today's Panchang and all 12 rashis: {iso_date}"
                thumbnail_text = "आज का पंचांग"
                color, symbol = "#406A8E", "☼"
            elif slot_type == "rashi_encyclopedia":
                offset = (day - start).days
                episode = (
                    "full" if offset < 12 else
                    ("career", "relationships", "remedies", "beliefs")[(offset - 12) // 12]
                )
                item, sign_hi, sign_en, color, symbol = _rashi_topic(
                    topics, rashi_index, slot_type, used, episode=episode,
                )
                rashi_index += 1
                topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                thumbnail_text = _thumbnail_text(topic_hi)
            elif slot_type == "rashi_encyclopedia_or_festival":
                offset = (day - start).days
                episode = (
                    "career" if offset < 12 else
                    ("relationships", "remedies", "beliefs")[(offset - 12) // 12]
                )
                item, sign_hi, sign_en, color, symbol = _rashi_topic(
                    topics, offset, slot_type, used, episode=episode,
                )
                topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                thumbnail_text = _thumbnail_text(topic_hi)
            elif slot_type in {"festival_explainer", "upcoming_festival"}:
                selected = None
                for event in event_candidates:
                    item = _event_topic(topics, event, slot_type, used, iso_date)
                    if item:
                        selected = event, item
                        break
                if not selected:
                    if event_candidates:
                        names = ", ".join(event["name_en"] for event in event_candidates)
                        raise CalendarBuildError(
                            f"No matching topic for verified festival(s) {names} "
                            f"on {iso_date}, slot {slot_no}"
                        )
                    row_type = (
                        "regional_customs"
                        if slot_type == "festival_explainer"
                        else "evening_special"
                    )
                    item = _topic_for(topics, row_type, used, iso_date)
                    topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                    thumbnail_text = _thumbnail_text(topic_hi)
                    note = (
                        "unverified festival topic not scheduled; evergreen "
                        f"{row_type} substituted"
                    )
                else:
                    event, item = selected
                    topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                    festival_date = event["date"]
                    festival_tradition = event["tradition"]
                    thumbnail_text = _thumbnail_text(topic_hi)
                    lead = (dt.date.fromisoformat(festival_date) - day).days
                    if lead < lead_min:
                        note = "late_prepublish"
            else:
                item = _topic_for(topics, slot_type, used, iso_date)
                topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                thumbnail_text = _thumbnail_text(topic_hi)

            title_key = topic_hi.casefold()
            if title_key in used and slot_type == "daily_panchang_rashifal":
                raise CalendarBuildError(f"Duplicate planned topic: {topic_hi}")
            used.add(title_key)
            row = {
                "date": iso_date,
                "slot": slot_no,
                "publish_time_ist": slot["publish_time_ist"],
                "type": row_type,
                "topic_hi": topic_hi,
                "topic_en": topic_en,
                "festival_date": festival_date,
                "thumbnail_text_hi": thumbnail_text,
                "thumbnail_color": color,
                "thumbnail_symbol": symbol,
                "status": status,
                "youtube_video_id": "",
                "drive_link": "",
                "festival_tradition": festival_tradition,
                "notes": note,
            }
            old = previous.get((iso_date, slot_no))
            if status == "planned" and old and old.get("status") in {
                "generated", "scheduled", "uploaded", "failed_saved_to_drive",
            }:
                for field in ("status", "youtube_video_id", "drive_link"):
                    row[field] = old.get(field, row[field])
                row["notes"] = old.get("notes") or note
            day_rows.append(row)
        if any(day_rows[index]["type"] == day_rows[index - 1]["type"]
               for index in range(1, len(day_rows))):
            raise CalendarBuildError(f"Adjacent slots repeat the same content type on {iso_date}")
        rows.extend(day_rows)
        day += dt.timedelta(days=1)

    return {
        "schema_version": 1,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "Asia/Kolkata",
        "videos": rows,
    }


def render_markdown(payload):
    lines = [
        "# Parv Katha content calendar",
        "",
        f"Date range: {payload['start_date']} to {payload['end_date']} (Asia/Kolkata)",
        "",
        "> Festival and vrat videos are scheduled only for verified dates. When no verified "
        "event fits a festival slot, an evergreen non-festival topic fills it instead.",
        "",
    ]
    current_date = None
    videos = payload["videos"]
    for index, row in enumerate(videos):
        if row["date"] != current_date:
            current_date = row["date"]
            lines.extend([
                f"## {current_date}",
                "",
                "| Slot | Time IST | Type | Topic | Festival date | Tradition | Status |",
                "|---:|:---:|---|---|:---:|---|---|",
            ])
        topic = row["topic_hi"].replace("|", "\\|")
        lines.append(
            f"| {row['slot']} | {row['publish_time_ist']} | {row['type']} | {topic} "
            f"| {row['festival_date']} | {row['festival_tradition']} | {row['status']} |"
        )
        if index + 1 < len(videos) and row["date"] != videos[index + 1]["date"]:
            lines.append("")
    return "\n".join(lines) + "\n"


def write_calendar(output_dir, payload):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "content_calendar.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "content_calendar.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CALENDAR_FIELDS)
        writer.writeheader()
        writer.writerows(payload["videos"])
    (output_dir / "CALENDAR.md").write_text(render_markdown(payload), encoding="utf-8")


def build(start_date, end_date, **kwargs):
    payload = build_rows(start_date, end_date, **kwargs)
    write_calendar(CALENDAR_DIR, payload)
    return payload


def print_summary(payload):
    rows = payload["videos"]
    dates = sorted({row["date"] for row in rows})
    planned_counts = {
        date: sum(row["date"] == date and row["status"] == "planned" for row in rows)
        for date in dates
    }
    try:
        upload_limit = int(os.getenv("MAX_API_UPLOADS_PER_DAY", "10"))
    except ValueError as exc:
        raise CalendarBuildError("MAX_API_UPLOADS_PER_DAY must be a non-negative integer") from exc
    if upload_limit < 0:
        raise CalendarBuildError("MAX_API_UPLOADS_PER_DAY must be a non-negative integer")
    blocked = sum(row["status"] == "blocked_unverified" for row in rows)
    planned = sum(planned_counts.values())
    api_uploads = sum(min(count, upload_limit) for count in planned_counts.values())
    drive_fallback = planned - api_uploads
    short_days = [
        f"{date} ({planned_counts[date]})"
        for date in dates if planned_counts[date] < 10
    ]
    print(f"Days: {len(dates)}; slot records: {len(rows)}; planned videos: {planned}")
    print(f"Blocked unverified slots: {blocked}")
    print(
        f"Daily planned videos: {min(planned_counts.values())}-"
        f"{max(planned_counts.values())}; fewer than 10: "
        + (", ".join(short_days) if short_days else "none")
    )
    print(
        f"YouTube API attempts reserved: {api_uploads}; pre-reserved Drive slots: "
        f"{drive_fallback}; upload failures use Drive fallback when assets exist"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start_date", default="2026-11-18")
    parser.add_argument("--to", dest="end_date", default="2026-12-31")
    args = parser.parse_args()
    try:
        payload = build(args.start_date, args.end_date)
    except CalendarBuildError as exc:
        raise SystemExit(f"Calendar not generated: {exc}") from exc
    print(f"Wrote {len(payload['videos'])} videos to calendar/content_calendar.csv/json and CALENDAR.md")
    try:
        print_summary(payload)
    except CalendarBuildError as exc:
        raise SystemExit(f"Calendar summary failed: {exc}") from exc


if __name__ == "__main__":
    main()
