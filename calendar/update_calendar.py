"""Merge per-video run results into the persistent CSV/JSON/Markdown calendar."""

import argparse
import json
import re
from pathlib import Path

from build_calendar import write_calendar


def merge_results(calendar_path, result_dir):
    calendar_path = Path(calendar_path)
    payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    rows = payload.get("videos", [])
    by_slot = {(row["date"], str(row["slot"])): row for row in rows}

    for result_path in sorted(Path(result_dir).glob("RESULT_*.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        key = (result.get("date"), str(result.get("slot")))
        if key not in by_slot:
            raise ValueError(f"Run result does not match a calendar slot: {result_path.name}")
        row = by_slot[key]
        if row.get("source") == "legacy" or row.get("type") == "legacy_daily":
            raise ValueError(f"Run result cannot update the Apps Script legacy slot: {result_path.name}")
        status = result.get("status")
        if status not in {"generated", "scheduled", "uploaded", "failed_saved_to_drive", "skipped"}:
            raise ValueError(f"Invalid run status in {result_path.name}: {status!r}")
        row["status"] = status
        youtube_status = result.get("youtube_status")
        if youtube_status not in {None, "scheduled", "failed", "not_attempted"}:
            raise ValueError(f"Invalid YouTube status in {result_path.name}: {youtube_status!r}")
        if youtube_status:
            row["youtube_status"] = youtube_status
        publish_time = result.get("publish_time_ist")
        if publish_time is not None:
            if not isinstance(publish_time, str) or not re.fullmatch(
                r"(?:[01]\d|2[0-3]):[0-5]\d", publish_time,
            ):
                raise ValueError(f"Invalid publish time in {result_path.name}: {publish_time!r}")
            row["publish_time_ist"] = publish_time
        row["youtube_video_id"] = (
            result.get("youtube_video_id") or row.get("youtube_video_id", "")
        )
        row["drive_link"] = result.get("drive_link") or row.get("drive_link", "")
        row["facebook_video_id"] = (
            result.get("facebook_video_id") or row.get("facebook_video_id", "")
        )
        row["facebook_link"] = (
            result.get("facebook_link") or row.get("facebook_link", "")
        )
        details = result.get("notes", "")
        notes = [
            part.strip()
            for value in (str(row.get("notes", "") or ""), str(details or ""))
            for part in value.split(";")
            if part.strip()
        ]
        row["notes"] = "; ".join(dict.fromkeys(notes))

    write_calendar(calendar_path.parent, payload)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    merge_results(args.calendar, args.results)


if __name__ == "__main__":
    main()
