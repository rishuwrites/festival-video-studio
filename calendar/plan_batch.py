"""Select planned videos for one publish date and reserve its upload budget."""

import argparse
import json
import os
from pathlib import Path

from upload_budget import allocate_uploads


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "calendar" / "content_calendar.json"


def plan_for_date(calendar_path, batch_date, upload_limit=None):
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
    invalid_rows = [
        row for row in day_rows
        if row.get("status") not in {"planned", "blocked_unverified"}
    ]
    if invalid_rows:
        raise ValueError(f"Calendar date {batch_date} has rows that are not dispatchable")
    selected = [
        row for row in rows
        if row.get("date") == batch_date and row.get("status") == "planned"
    ]
    if not selected:
        raise ValueError(f"No dispatchable planned videos for {batch_date}")
    return allocate_uploads(selected, limit=upload_limit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=os.environ.get("BATCH_DATE", ""))
    parser.add_argument("--calendar", type=Path, default=CALENDAR_PATH)
    args = parser.parse_args()
    if not args.date:
        parser.error("--date or BATCH_DATE is required")
    print(json.dumps(plan_for_date(args.calendar, args.date), ensure_ascii=False))


if __name__ == "__main__":
    main()
