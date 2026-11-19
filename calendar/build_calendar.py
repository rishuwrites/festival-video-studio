"""Build the 2026 long-form publishing calendar from owner-verified source data."""

import argparse
import csv
import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_DIR = ROOT / "calendar"
SLOTS_PATH = ROOT / "config" / "slots.json"
CHANNEL_FOCUS_PATH = ROOT / "config" / "channel_focus.json"
TOPIC_POOL_PATH = CALENDAR_DIR / "topic_pool.json"
LEGACY_CALENDAR_PATH = ROOT / "data" / "india-festival-video-calendar-2026.json"
FESTIVAL_DATES_PATH = ROOT / "data" / "festival_dates_2026.json"
PANCHANG_PATH = ROOT / "data" / "panchang_2026_11_18_to_12_31.csv"
OUTPUT_JSON = CALENDAR_DIR / "content_calendar.json"
CALENDAR_FIELDS = [
    "date", "slot", "publish_time_ist", "type", "source", "channel_category",
    "topic_hi", "topic_en",
    "festival_date", "festival_tradition", "thumbnail_text_hi", "thumbnail_color",
    "thumbnail_symbol", "status", "youtube_status", "youtube_video_id", "drive_link",
    "facebook_video_id", "facebook_link", "notes",
]
ALLOWED_STATUSES = {
    "planned", "generated", "scheduled", "uploaded",
    "failed_saved_to_drive", "skipped", "blocked_unverified",
    "blocked_duplicate", "legacy_managed",
}
ACTIVE_STATUSES = {
    "planned", "legacy_managed", "generated", "scheduled",
    "uploaded", "failed_saved_to_drive",
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


def _read_legacy_calendar(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise CalendarBuildError("Legacy calendar must contain an entries list")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise CalendarBuildError("Every legacy calendar entry must be an object")
        try:
            target_date = dt.date.fromisoformat(str(entry.get("date", "")))
        except ValueError as exc:
            raise CalendarBuildError(
                f"Invalid date in legacy calendar entry: {entry.get('date')!r}"
            ) from exc
        topic = str(entry.get("topic", "")).strip()
        if not topic:
            raise CalendarBuildError(f"Legacy calendar entry {target_date} has no topic")
        if target_date.isoformat() in result:
            raise CalendarBuildError(f"Duplicate legacy calendar entry for {target_date}")
        result[target_date.isoformat()] = entry
    return result


def _read_channel_focus(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("core_categories", "astrology_categories"):
        values = payload.get(key)
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) and value for value in values
        ):
            raise CalendarBuildError(f"channel_focus.json must define a non-empty {key} list")
    if set(payload["core_categories"]) & set(payload["astrology_categories"]):
        raise CalendarBuildError("Channel core and astrology categories must not overlap")
    try:
        minimum = float(payload["min_core_share"])
        max_astrology = int(payload["max_astrology_per_day"])
        max_rashi = int(payload["rashi_encyclopedia_max_per_week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarBuildError("Channel focus limits must be numeric") from exc
    if not 0 < minimum <= 1 or max_astrology < 0 or max_rashi < 0:
        raise CalendarBuildError("Channel focus limits are outside their valid range")
    return {
        "core_categories": set(payload["core_categories"]),
        "astrology_categories": set(payload["astrology_categories"]),
        "min_core_share": minimum,
        "max_astrology_per_day": max_astrology,
        "rashi_encyclopedia_max_per_week": max_rashi,
    }


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


def _normalized_words(value):
    return re.sub(r"[^\w]+", " ", str(value or "").casefold()).strip()


def _topic_identity(topic):
    topic_hi = str(topic.get("topic_hi", "")).strip()
    topic_en = str(topic.get("topic_en", "")).strip()
    for prefix in (
        "कथा और लोकस्मृति: ", "इतिहास की झलक: ", "आज के जीवन में अर्थ: ",
        "क्षेत्रीय विविधता: ", "व्रत परंपरा में क्षेत्रीय दृष्टि: ", "सांस्कृतिक चिंतन: ",
    ):
        if topic_hi.startswith(prefix):
            topic_hi = topic_hi[len(prefix):]
            break
    for prefix in (
        "Story and community memory: ", "A glimpse into history: ",
        "Meaning in contemporary life: ", "Regional perspective: ",
        "Regional perspective on vrat customs: ", "Devotional reflection: ",
    ):
        if topic_en.startswith(prefix):
            topic_en = topic_en[len(prefix):]
            break
    return _normalized_words(topic_hi), _normalized_words(topic_en)


def _legacy_entries_near(legacy_entries, publish_date, radius=2):
    publish_day = dt.date.fromisoformat(publish_date)
    nearby = []
    for entry in legacy_entries.values():
        target_day = dt.date.fromisoformat(entry["date"])
        legacy_release_day = target_day - dt.timedelta(days=2)
        if abs((legacy_release_day - publish_day).days) <= radius:
            nearby.append(entry)
    return nearby


def _duplicates_legacy(topic, legacy_entries):
    candidate_title = _normalized_words(
        f"{topic.get('topic_hi', '')} {topic.get('topic_en', '')}"
    )
    candidate_festival = _normalized_words(topic.get("festival_key", ""))
    candidate_words = set(candidate_title.split())
    stop_words = {"a", "an", "and", "for", "in", "of", "the", "to", "with"}
    candidate_words -= stop_words
    for entry in legacy_entries:
        legacy_text = _normalized_words(
            " ".join([
                entry.get("topic", ""),
                str(entry.get("festival") or ""),
                " ".join(entry.get("panchang_events", [])),
            ])
        )
        if not legacy_text:
            continue
        if candidate_title == legacy_text or (
            candidate_title and (candidate_title in legacy_text or legacy_text in candidate_title)
        ):
            return True
        legacy_terms = [
            _normalized_words(entry.get("festival", "")),
            *[_normalized_words(event) for event in entry.get("panchang_events", [])],
        ]
        if candidate_festival and any(
            term and (candidate_festival == term or candidate_festival in term or term in candidate_festival)
            for term in legacy_terms
        ):
            return True
        if any(
            len(term.split()) >= 2 and (term in candidate_title or candidate_title in term)
            for term in legacy_terms
        ):
            return True
        legacy_words = set(_normalized_words(entry.get("topic", "")).split()) - stop_words
        overlap = candidate_words & legacy_words
        if len(overlap) >= 3 and len(overlap) / min(len(candidate_words), len(legacy_words)) >= 0.75:
            return True
    return False


def _topic_for(topics, topic_type, used, publish_date, legacy_entries=(), used_today=None):
    for topic in topics:
        if topic.get("type") == topic_type and topic.get("evergreen") is True:
            key = topic["topic_hi"].casefold()
            if (
                key not in used
                and (used_today is None or _topic_identity(topic) not in used_today)
                and not _duplicates_legacy(topic, legacy_entries)
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


def _event_topic(topics, event, topic_type, used, publish_date, legacy_entries=(),
                 used_today=None):
    keys = {event["name_en"].casefold(), event["name_hi"].casefold()}
    for topic in topics:
        if topic.get("type") != topic_type:
            continue
        if str(topic.get("festival_key", "")).casefold() not in keys:
            continue
        if not topic.get("earliest_date", "") <= publish_date <= topic.get("latest_date", "9999-12-31"):
            continue
        title = topic["topic_hi"].casefold()
        if (
            title not in used
            and (used_today is None or _topic_identity(topic) not in used_today)
            and not _duplicates_legacy(topic, legacy_entries)
        ):
            used.add(title)
            return topic
    return None


def _rashi_topic(topics, rashi_index, topic_type, used, episode=None, legacy_entries=(),
                 used_today=None):
    sign_hi, sign_en, color, symbol = RASHIS[rashi_index % len(RASHIS)]
    candidates = [
        item for item in topics
        if item.get("type") == topic_type
        and item.get("rashi_index") == rashi_index % len(RASHIS)
        and (episode is None or item.get("episode") == episode)
    ]
    for topic in candidates:
        key = topic["topic_hi"].casefold()
        if (
            key not in used
            and (used_today is None or _topic_identity(topic) not in used_today)
            and not _duplicates_legacy(topic, legacy_entries)
        ):
            used.add(key)
            return topic, sign_hi, sign_en, color, symbol
    raise CalendarBuildError(f"No unused {topic_type} topic for {sign_en}")


def _validate_day_focus(day_rows, focus, calendar_date):
    active = [
        row for row in day_rows
        if row["status"] in ACTIVE_STATUSES
    ]
    if not active:
        return
    core_count = sum(
        row["type"] in focus["core_categories"] or row["source"] == "legacy"
        for row in active
    )
    core_share = core_count / len(active)
    if core_share < focus["min_core_share"]:
        raise CalendarBuildError(
            f"Channel focus violation on {calendar_date}: core share "
            f"{core_count}/{len(active)} ({core_share:.0%}) is below "
            f"{focus['min_core_share']:.0%}"
        )
    astrology_count = sum(
        row["type"] in focus["astrology_categories"] for row in active
    )
    if astrology_count > focus["max_astrology_per_day"]:
        raise CalendarBuildError(
            f"Channel focus violation on {calendar_date}: {astrology_count} astrology videos "
            f"exceed the daily maximum of {focus['max_astrology_per_day']}"
        )


def _thumbnail_text(topic):
    words = topic.split()
    text = " ".join(words[:4])
    return text if len(text.split()) >= 2 else f"{text} विशेष"


def build_rows(start_date, end_date, slots_path=SLOTS_PATH, topic_pool_path=TOPIC_POOL_PATH,
               festivals_path=FESTIVAL_DATES_PATH, panchang_path=PANCHANG_PATH,
               previous_path=OUTPUT_JSON, channel_focus_path=CHANNEL_FOCUS_PATH,
               legacy_calendar_path=LEGACY_CALENDAR_PATH):
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
    if len({slot.get("publish_time_ist") for slot in slots}) != 10:
        raise CalendarBuildError("Every daily slot must have a unique publish time")
    legacy_slots = [
        slot for slot in slots
        if slot.get("source") == "legacy" and slot.get("type") == "legacy_daily"
    ]
    if (
        len(legacy_slots) != 1
        or legacy_slots[0].get("publish_time_ist") != "09:00"
        or sum(slot.get("source") == "legacy" for slot in slots) != 1
        or any(slot.get("source") not in {"legacy", "batch"} for slot in slots)
    ):
        raise CalendarBuildError(
            "config/slots.json must define one legacy_daily slot at 09:00 and batch slots"
        )

    festivals, unverified = _read_festivals(festivals_path)
    if unverified:
        print("Festival/vrat dates still requiring owner verification:")
        print("\n".join(unverified))
    panchang = _read_panchang(panchang_path, start, end)
    topics = _read_topic_pool(topic_pool_path)
    focus = _read_channel_focus(channel_focus_path)
    legacy_entries = _read_legacy_calendar(legacy_calendar_path)
    previous = _previous_rows(previous_path)
    used = set()
    rows = []
    day = start
    rashi_index = 0
    rashi_counts_by_week = {}
    lead_min = int(os.getenv("PRE_PUBLISH_DAYS_MIN", "2"))
    lead_max = int(os.getenv("PRE_PUBLISH_DAYS_MAX", "3"))
    if lead_min < 2 or lead_max > 3 or lead_min > lead_max:
        raise CalendarBuildError("PRE_PUBLISH_DAYS_MIN/MAX must be an ordered subset of 2 to 3")

    while day <= end:
        iso_date = day.isoformat()
        day_rows = []
        used_today = set()
        week_key = (day.isocalendar().year, day.isocalendar().week)
        include_rashi = (
            day.weekday() in {1, 4}
            and rashi_counts_by_week.get(week_key, 0)
            < focus["rashi_encyclopedia_max_per_week"]
        )
        legacy_release_target = (day + dt.timedelta(days=2)).isoformat()
        legacy_entry = legacy_entries.get(legacy_release_target)
        nearby_legacy = _legacy_entries_near(legacy_entries, iso_date)
        event_candidates = _verified_events_for(
            festivals, iso_date, lead_min, lead_max, start.isoformat(),
        )
        for slot in slots:
            slot_no = int(slot["slot"])
            slot_type = slot["type"]
            source = slot["source"]
            row_type = slot_type
            channel_category = slot_type
            festival_date = ""
            festival_tradition = ""
            note = ""
            status = "planned"
            row_type = slot_type
            color, symbol = "#8B6B9E", "✦"
            old = previous.get((iso_date, slot_no))
            if old and old.get("status") in {
                "generated", "scheduled", "uploaded", "failed_saved_to_drive",
            }:
                row = dict(old)
                day_rows.append(row)
                used.add(str(row.get("topic_hi", "")).casefold())
                used_today.add(_topic_identity(row))
                if row.get("type") == "rashi_encyclopedia":
                    rashi_index += 1
                    rashi_counts_by_week[week_key] = rashi_counts_by_week.get(week_key, 0) + 1
                continue
            if slot_type == "legacy_daily":
                if legacy_entry:
                    topic_hi = topic_en = legacy_entry["topic"]
                    source = "legacy"
                    status = "legacy_managed"
                    channel_category = "legacy_daily"
                    note = (
                        f"Managed by Apps Script; topic comes from legacy target "
                        f"{legacy_release_target} and releases two days earlier"
                    )
                else:
                    source = "batch"
                    row_type = "regional_customs"
                    channel_category = row_type
                    item = _topic_for(
                        topics, row_type, used, iso_date, nearby_legacy,
                        used_today=used_today,
                    )
                    topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                    note = "No legacy calendar entry for this release date; batch fills the slot"
                thumbnail_text = _thumbnail_text(topic_hi)
            elif slot_type == "daily_panchang_rashifal":
                row_type = "tithi_and_dates" if include_rashi else slot_type
                channel_category = row_type
                topic_hi = f"आज का पंचांग: तिथि, नक्षत्र और राहु काल ({iso_date})"
                topic_en = f"Today's panchang: tithi, nakshatra, and Rahu Kaal ({iso_date})"
                thumbnail_text = "आज का पंचांग"
                color, symbol = "#406A8E", "☼"
            elif slot_type == "evergreen_culture" and include_rashi:
                item, sign_hi, sign_en, color, symbol = _rashi_topic(
                    topics,
                    rashi_index,
                    "rashi_encyclopedia",
                    used,
                    episode="full",
                    legacy_entries=nearby_legacy,
                    used_today=used_today,
                )
                rashi_index += 1
                rashi_counts_by_week[week_key] = rashi_counts_by_week.get(week_key, 0) + 1
                row_type = "rashi_encyclopedia"
                channel_category = row_type
                topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                thumbnail_text = _thumbnail_text(topic_hi)
            elif slot_type in {"festival_explainer", "upcoming_festival"}:
                selected = None
                for event in event_candidates:
                    item = _event_topic(
                        topics, event, slot_type, used, iso_date, nearby_legacy,
                        used_today=used_today,
                    )
                    if item:
                        selected = event, item
                        break
                if not selected:
                    reason = (
                        "duplicate legacy topic"
                        if event_candidates
                        else "unverified festival topic"
                    )
                    row_type = (
                        "regional_customs"
                        if slot_type == "festival_explainer"
                        else "story_history"
                    )
                    channel_category = row_type
                    item = _topic_for(
                        topics, row_type, used, iso_date, nearby_legacy,
                        used_today=used_today,
                    )
                    topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                    thumbnail_text = _thumbnail_text(topic_hi)
                    note = (
                        f"{reason} not scheduled; evergreen {row_type} substituted"
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
                item = _topic_for(
                    topics, slot_type, used, iso_date, nearby_legacy,
                    used_today=used_today,
                )
                topic_hi, topic_en = item["topic_hi"], item["topic_en"]
                thumbnail_text = _thumbnail_text(topic_hi)

            identity = _topic_identity({"topic_hi": topic_hi, "topic_en": topic_en})
            if identity in used_today:
                raise CalendarBuildError(f"Duplicate topic subject on {iso_date}: {topic_hi}")
            used_today.add(identity)
            title_key = topic_hi.casefold()
            if status == "legacy_managed" and title_key in used:
                raise CalendarBuildError(f"Duplicate planned topic: {topic_hi}")
            used.add(title_key)
            row = {
                "date": iso_date,
                "slot": slot_no,
                "publish_time_ist": slot["publish_time_ist"],
                "type": row_type,
                "source": source,
                "channel_category": channel_category,
                "topic_hi": topic_hi,
                "topic_en": topic_en,
                "festival_date": festival_date,
                "thumbnail_text_hi": thumbnail_text,
                "thumbnail_color": color,
                "thumbnail_symbol": symbol,
                "status": status,
                "youtube_status": "not_attempted",
                "youtube_video_id": "",
                "drive_link": "",
                "facebook_video_id": "",
                "facebook_link": "",
                "festival_tradition": festival_tradition,
                "notes": note,
            }
            if status in {"planned", "legacy_managed"} and old and old.get("status") in {
                "generated", "scheduled", "uploaded", "failed_saved_to_drive",
                "legacy_managed",
            }:
                for field in (
                    "status", "youtube_status", "youtube_video_id", "drive_link",
                    "facebook_video_id", "facebook_link",
                ):
                    row[field] = old.get(field, row[field])
                row["notes"] = old.get("notes") or note
            day_rows.append(row)
        if len(day_rows) != 10:
            raise CalendarBuildError(f"Expected 10 slots on {iso_date}; found {len(day_rows)}")
        _validate_day_focus(day_rows, focus, iso_date)
        rows.extend(day_rows)
        day += dt.timedelta(days=1)

    for (year, week), count in rashi_counts_by_week.items():
        if count > focus["rashi_encyclopedia_max_per_week"]:
            raise CalendarBuildError(
                f"Channel focus violation: ISO week {year}-W{week:02} has "
                f"{count} rashi episodes; maximum is "
                f"{focus['rashi_encyclopedia_max_per_week']}"
            )
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
        "> The 09:00 `legacy_daily` slot is owned by Apps Script and is never rendered by the batch. "
        "Unverified or legacy-duplicate festival topics are replaced with evergreen core-culture "
        "videos. All ten slots remain active and are checked against the configured channel focus.",
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
                "| Slot | Time IST | Source | Type | Topic | Festival date | Tradition | Status |",
                "|---:|:---:|---|---|---|:---:|---|---|",
            ])
        topic = row["topic_hi"].replace("|", "\\|")
        lines.append(
            f"| {row['slot']} | {row['publish_time_ist']} | {row['source']} "
            f"| {row['type']} | {topic} "
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
    focus = _read_channel_focus(CHANNEL_FOCUS_PATH)
    blocked = sum(row["status"] == "blocked_unverified" for row in rows)
    duplicate_blocked = sum(row["status"] == "blocked_duplicate" for row in rows)
    evergreen_replacements = sum(
        "not scheduled; evergreen" in row["notes"] for row in rows
    )
    batch_planned = sum(
        row["source"] == "batch" and row["status"] == "planned" for row in rows
    )
    legacy_count = sum(row["source"] == "legacy" for row in rows)
    print(
        f"Days: {len(dates)}; slot records: {len(rows)}; "
        f"legacy-managed: {legacy_count}; planned batch videos: {batch_planned}"
    )
    print(f"Blocked unverified slots: {blocked}")
    print(f"Blocked due to nearby legacy duplicates: {duplicate_blocked}")
    active_total = 0
    core_total = 0
    astrology_total = 0
    active_counts = []
    for calendar_date in dates:
        day_rows = [row for row in rows if row["date"] == calendar_date]
        active = [
            row for row in day_rows
            if row["status"] in ACTIVE_STATUSES
        ]
        legacy_for_day = sum(row["source"] == "legacy" for row in active)
        api_attempts = len(active)
        active_counts.append(len(active))
        active_total += len(active)
        core_count = sum(
            row["source"] == "legacy" or row["type"] in focus["core_categories"]
            for row in active
        )
        astrology_count = sum(
            row["type"] in focus["astrology_categories"] for row in active
        )
        core_total += core_count
        astrology_total += astrology_count
        mix = {}
        for row in active:
            mix[row["type"]] = mix.get(row["type"], 0) + 1
        print(
            f"{calendar_date}: videos={len(active)}/10 slots; "
            f"legacy={legacy_for_day}; core={core_count}/{len(active)}; "
            f"astrology={astrology_count}; YouTube API attempts={api_attempts}; "
            "Drive fallback=on failure; "
            f"mix={mix}"
        )
    short_days = [
        f"{calendar_date} ({active_counts[index]})"
        for index, calendar_date in enumerate(dates)
        if active_counts[index] < 10
    ]
    core_share = core_total / active_total if active_total else 0
    astrology_share = astrology_total / active_total if active_total else 0
    print(
        f"Active video total: {active_total}; core: {core_total} "
        f"({core_share:.1%}); astrology: {astrology_total} ({astrology_share:.1%})"
    )
    print(
        f"YouTube API attempts planned: {active_total}; Drive fallback is attempted only "
        f"after an upload failure; evergreen replacements: {evergreen_replacements}"
    )
    print("Days below 10 videos: " + (", ".join(short_days) if short_days else "none"))


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
