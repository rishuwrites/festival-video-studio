"""Select planned videos for one publish date and reserve its upload budget."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from upload_budget import allocate_uploads


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "calendar" / "content_calendar.json"


def plan_for_date(calendar_path, batch_date, retry_failed=False, now=None):
    payload = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("videos")
    if not isinstance(rows, list):
        raise ValueError("content_calendar.json must contain a videos list")
    day_rows = [
        row for row in rows
        if row.get("date") == batch_date
    ]
    if len(day_rows) != 10 or {int(row.get("slot", 0)) for row in day_rows} != set(range(1, 11)):
        raise ValueError(f"Calendar slots for {batch_date} must be exactly 1 through 10")
    legacy_rows = [
        row for row in day_rows
        if row.get("source") == "legacy" or row.get("type") == "legacy_daily"
    ]
    if len(legacy_rows) > 1:
        raise ValueError(f"Calendar date {batch_date} has more than one legacy slot")
    if any(row.get("status") != "legacy_managed" for row in legacy_rows):
        raise ValueError(f"Legacy slot for {batch_date} must be managed by Apps Script")
    batch_rows = [row for row in day_rows if row not in legacy_rows]
    expected_batch_rows = 9 if legacy_rows else 10
    if len(batch_rows) != expected_batch_rows:
        raise ValueError(
            f"Calendar date {batch_date} must have {expected_batch_rows} batch slots "
            f"alongside {len(legacy_rows)} legacy slot(s)"
        )
    if retry_failed:
        retryable_statuses = {
            "planned", "generated", "scheduled", "failed_saved_to_drive", "skipped",
        }
        current = now or dt.datetime.now(ZoneInfo("Asia/Kolkata"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        earliest = current + dt.timedelta(minutes=15)
        selected = []
        for row in batch_rows:
            if (
                row.get("status") not in retryable_statuses
                or row.get("youtube_video_id")
            ):
                continue
            publish_at = dt.datetime.fromisoformat(
                f"{row['date']}T{row['publish_time_ist']}:00+05:30"
            )
            if publish_at > earliest:
                selected.append(row)
    else:
        invalid_rows = [
            row for row in batch_rows
            if row.get("status") not in {
                "planned", "blocked_unverified", "blocked_duplicate",
            }
        ]
        if invalid_rows:
            raise ValueError(f"Calendar date {batch_date} has rows that are not dispatchable")
        selected = [
            row for row in batch_rows
            if row.get("status") == "planned"
        ]
    if not selected:
        label = "failed videos" if retry_failed else "planned videos"
        raise ValueError(f"No dispatchable {label} for {batch_date}")
    return allocate_uploads(selected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=os.environ.get("BATCH_DATE", ""))
    parser.add_argument("--calendar", type=Path, default=CALENDAR_PATH)
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        default=os.environ.get("RETRY_FAILED", "").strip().casefold() in {"1", "true", "yes"},
    )
    args = parser.parse_args()
    if not args.date:
        parser.error("--date or BATCH_DATE is required")
    print(json.dumps(
        plan_for_date(args.calendar, args.date, retry_failed=args.retry_failed),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
