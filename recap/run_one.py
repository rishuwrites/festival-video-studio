"""Render and publish one calendar video, retaining failures in Google Drive."""

import json
import os
import re
import sys
import time
from pathlib import Path

import festival_main
import gemini
import rashi_encyclopedia
import rashifal
from drive_fallback import DriveFallbackError, save_to_drive


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "output"
RESULTS_ROOT = ROOT / "output" / "run_results"
MAX_RETRIES = 2


def _extra_options(raw, default_scope=None):
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("EXTRA_ARGS must be a JSON list of strings") from exc
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("EXTRA_ARGS must be a JSON list of strings")
    scope = default_scope or festival_main.S.DEFAULT_SCOPE
    facebook_upload = False
    index = 0
    while index < len(values):
        value = values[index]
        if value in ("--scope", "--location"):
            index += 1
            if index >= len(values) or not values[index].strip():
                raise ValueError(f"{value} requires a non-empty value")
            scope = values[index]
        elif value == "--facebook-upload":
            facebook_upload = True
        else:
            raise ValueError(f"Unsupported EXTRA_ARGS option: {value}")
        index += 1
    return scope, facebook_upload


def _quota_error(error):
    message = str(error).casefold()
    return "uploadlimitexceeded" in message or "quotaexceeded" in message


def _enabled(value):
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _video_files(output_dir):
    output_dir = Path(output_dir)
    videos = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    for video in videos:
        stem = video.stem
        metadata = output_dir / f"{stem}.json"
        thumbnail = output_dir / f"{stem}.jpg"
        if metadata.is_file() and thumbnail.is_file():
            return video, thumbnail, metadata
    return None, None, None


def _write_result(result_dir, result):
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    path = result_dir / f"RESULT_{result['date']}_{result['slot']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _prepared_content(content_type, topic, publish_date, festival_date):
    if content_type == "daily_panchang_rashifal":
        return rashifal.build_panchang_content(
            publish_date, include_rashifal=True,
        )
    if content_type == "tithi_and_dates":
        return rashifal.build_panchang_content(
            publish_date, include_rashifal=False,
        )
    if content_type == "rashi_encyclopedia" and not festival_date:
        rashi_name = topic.split(":", 1)[0].removesuffix(" राशि").strip()
        return rashi_encyclopedia.build_rashi_content(rashi_name)
    return None


def run_one(env=None):
    env = env or os.environ
    topic = env.get("TOPIC", "").strip()
    if not topic:
        raise ValueError("TOPIC is required")
    content_type = env.get("CONTENT_TYPE", "").strip()
    if content_type == "legacy_daily" or env.get("SOURCE", "").strip() == "legacy":
        raise ValueError("Legacy daily videos are managed by Apps Script, not recap/run_one.py")
    publish_date = env.get("PUBLISH_DATE", "").strip()
    publish_time = env.get("PUBLISH_TIME", "").strip()
    calendar_date = env.get("CALENDAR_DATE", publish_date).strip()
    festival_date = env.get("FEST_DATE", "").strip()
    festival_tradition = env.get("FESTIVAL_TRADITION", "").strip()
    slot = int(env.get("SLOT", "0"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publish_date):
        raise ValueError("PUBLISH_DATE must use YYYY-MM-DD")
    if not re.fullmatch(r"\d{2}:\d{2}", publish_time):
        raise ValueError("PUBLISH_TIME must use 24-hour HH:MM IST")
    if slot not in range(1, 11):
        raise ValueError("SLOT must be from 1 through 10")
    scope, facebook_option = _extra_options(
        env.get("EXTRA_ARGS", "[]"), env.get("FESTIVAL_SCOPE", "").strip(),
    )
    facebook_upload = facebook_option or _enabled(env.get("FACEBOOK_UPLOAD"))
    output_dir = Path(env.get("OUTPUT_DIR", OUTPUT_ROOT / f"{calendar_date}_slot_{slot}"))
    result_dir = Path(env.get("RESULTS_DIR", RESULTS_ROOT))
    allowed = env.get("UPLOAD_ALLOWED", "false").strip().casefold() in {"1", "true", "yes"}
    prepared = _prepared_content(content_type, topic, publish_date, festival_date)
    if prepared and content_type == "daily_panchang_rashifal":
        prepared["description_disclaimer"] = rashifal.DISCLAIMER
    content_date = (
        publish_date if content_type == "daily_panchang_rashifal"
        else festival_date
    )

    gemini.reset_request_count()
    generated = None
    last_error = None
    attempts = 1 if not allowed else MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            generated = festival_main.generate_video(
                topic=topic,
                date=content_date,
                scope=scope,
                output_dir=str(output_dir),
                publish_date=publish_date,
                publish_time=publish_time,
                upload=allowed,
                facebook_upload_enabled=facebook_upload,
                prepared_bundle=prepared,
                title_max_length=69,
                title_suffix=f"{publish_date} Slot {slot}",
                festival_tradition=festival_tradition,
                continue_on_upload_errors=facebook_upload,
                allow_existing_upload=True,
            )
            break
        except Exception as exc:
            last_error = exc
            print(f"Video attempt {attempt}/{attempts} failed: {type(exc).__name__}: {exc}")
            if not allowed or _quota_error(exc) or attempt == attempts:
                break
            time.sleep(min(2 ** attempt, 8))

    gemini_requests = gemini.get_request_count()
    print(f"Gemini requests used for this video: {gemini_requests}")
    if generated:
        metadata = json.loads(Path(generated["metadata"]).read_text(encoding="utf-8"))
        if allowed and (generated.get("youtube") or generated.get("facebook")):
            drive_link = ""
            upload_errors = generated.get("upload_errors", {})
            if upload_errors:
                try:
                    drive = save_to_drive(
                        generated["video"],
                        generated["thumbnail"],
                        generated["metadata"],
                        slot,
                        "partial_upload_failure",
                        publish_date=publish_date,
                        publish_time=publish_time,
                        calendar_date=calendar_date,
                    )
                    drive_link = drive["drive_link"]
                except (DriveFallbackError, OSError, ValueError, RuntimeError) as exc:
                    upload_errors["drive"] = f"{type(exc).__name__}: {exc}"
            result = {
                "date": calendar_date,
                "slot": slot,
                "status": "scheduled",
                "youtube_status": (
                    "scheduled" if metadata.get("youtube_video_id") else "failed"
                ),
                "youtube_video_id": metadata.get("youtube_video_id", ""),
                "drive_link": drive_link,
                "facebook_video_id": metadata.get("facebook_video_id", ""),
                "facebook_link": metadata.get("facebook_url", ""),
                "notes": "; ".join([
                    f"Gemini requests: {gemini_requests}",
                    *[
                        f"{platform} upload failed: {detail}"
                        for platform, detail in upload_errors.items()
                    ],
                ]),
            }
            _write_result(result_dir, result)
            return result
        video_path, thumbnail_path, metadata_path = (
            generated["video"], generated["thumbnail"], generated["metadata"],
        )
        reason = "quota_reserved" if not allowed else "upload_failed"
    else:
        video_path, thumbnail_path, metadata_path = _video_files(output_dir)
        reason = "youtube_quota" if _quota_error(last_error) else "generation_or_upload_failed"

    if video_path and thumbnail_path and metadata_path:
        try:
            drive = save_to_drive(
                video_path,
                thumbnail_path,
                metadata_path,
                slot,
                reason,
                publish_date=publish_date,
                publish_time=publish_time,
                calendar_date=calendar_date,
            )
            result = {
                "date": calendar_date,
                "slot": slot,
                "status": (
                    "scheduled"
                    if generated and (
                        metadata.get("youtube_video_id") or metadata.get("facebook_video_id")
                    )
                    else "failed_saved_to_drive"
                ),
                "youtube_status": (
                    "scheduled"
                    if generated and metadata.get("youtube_video_id")
                    else "failed"
                ),
                "youtube_video_id": "",
                "drive_link": drive["drive_link"],
                "facebook_video_id": metadata.get("facebook_video_id", "") if generated else "",
                "facebook_link": metadata.get("facebook_url", "") if generated else "",
                "notes": "; ".join([
                    reason,
                    f"Gemini requests: {gemini_requests}",
                    *[
                        f"{platform} upload failed: {detail}"
                        for platform, detail in (generated.get("upload_errors", {}) if generated else {}).items()
                    ],
                ]),
            }
            _write_result(result_dir, result)
            return result
        except (DriveFallbackError, OSError, ValueError, RuntimeError) as exc:
            fallback_error = f"Drive fallback failed: {type(exc).__name__}: {exc}"
    else:
        fallback_error = "Drive fallback unavailable: generated video, thumbnail, or metadata is missing"

    notes = [
        f"Gemini requests: {gemini_requests}",
        str(last_error) if last_error else "YouTube upload was reserved by the daily quota budget",
        *[
            f"{platform} upload failed: {detail}"
            for platform, detail in (generated.get("upload_errors", {}) if generated else {}).items()
        ],
        fallback_error,
    ]
    result = {
        "date": calendar_date,
        "slot": slot,
        "status": "skipped",
        "youtube_status": "failed",
        "youtube_video_id": "",
        "drive_link": "",
        "facebook_video_id": "",
        "facebook_link": "",
        "notes": "; ".join(note for note in notes if note),
    }
    _write_result(result_dir, result)
    print(result["notes"])
    return result


def main():
    try:
        result = run_one()
    except (ValueError, OSError) as exc:
        print(f"Could not run calendar video: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if result.get("youtube_status") != "scheduled" or not result.get("youtube_video_id"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
