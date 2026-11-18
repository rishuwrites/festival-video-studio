"""Re-upload Drive-saved videos after YouTube upload quota becomes available."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import requests

import drive_fallback
from youtube_upload import upload_scheduled


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "output" / "retry_results"


def _list_files(token, query):
    files = []
    page_token = ""
    while True:
        params = {
            "q": query,
            "fields": "nextPageToken,files(id,name,mimeType,webViewLink)",
            "pageSize": 1000,
        }
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(
            f"{drive_fallback.DRIVE_API}/files",
            headers=drive_fallback._headers(token),
            params=params,
            timeout=30,
        )
        drive_fallback._check(response, "retry file listing")
        payload = response.json()
        files.extend(payload.get("files", []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            return files


def _download(token, file_id, path):
    response = requests.get(
        f"{drive_fallback.DRIVE_API}/files/{file_id}",
        headers=drive_fallback._headers(token),
        params={"alt": "media"},
        stream=True,
        timeout=(30, 600),
    )
    drive_fallback._check(response, "file download")
    with Path(path).open("wb") as file:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                file.write(chunk)


def _update_drive_metadata(token, file_id, metadata):
    response = requests.patch(
        f"{drive_fallback.DRIVE_API}/files/{file_id}",
        headers={
            **drive_fallback._headers(token),
            "Content-Type": "application/json",
        },
        params={"uploadType": "media"},
        data=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        timeout=60,
    )
    drive_fallback._check(response, "metadata update")


def _write_result(result_dir, result):
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    path = result_dir / f"RESULT_{result['date']}_{result['slot']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def retry_failed_uploads(result_dir=RESULTS_DIR):
    token = drive_fallback.oauth_access_token()
    root = drive_fallback._find_folder(token, drive_fallback.ROOT_FOLDER_NAME)
    folders = _list_files(
        token,
        f"'{root['id']}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
    )
    retried = []
    for folder in folders:
        files = _list_files(token, f"'{folder['id']}' in parents and trashed=false")
        by_name = {item["name"]: item for item in files}
        videos = [item for item in files if item["name"].casefold().endswith(".mp4")]
        for video in videos:
            stem = Path(video["name"]).stem
            metadata_file = by_name.get(f"{stem}.json")
            thumbnail_file = by_name.get(f"{stem}.jpg")
            if not metadata_file or not thumbnail_file:
                print(f"Skipping {video['name']}: its metadata or thumbnail is missing")
                continue
            with tempfile.TemporaryDirectory(prefix="parv-katha-retry-") as temp_dir:
                video_path = Path(temp_dir) / video["name"]
                metadata_path = Path(temp_dir) / metadata_file["name"]
                thumbnail_path = Path(temp_dir) / thumbnail_file["name"]
                _download(token, video["id"], video_path)
                _download(token, metadata_file["id"], metadata_path)
                _download(token, thumbnail_file["id"], thumbnail_path)
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("youtube_video_id") or metadata.get("upload_status") in {
                    "scheduled_public", "uploaded",
                }:
                    print(f"Skipping {video['name']}: it is already marked as uploaded")
                    continue
                slot = int(metadata.get("slot", 0))
                if slot not in range(1, 11):
                    print(f"Skipping {video['name']}: invalid calendar slot")
                    continue
                calendar_date = metadata.get("calendar_date", "")
                if not calendar_date:
                    print(f"Skipping {video['name']}: calendar date is missing")
                    continue
                publish_date = metadata.get("publish_date", "")
                publish_time = metadata.get("publish_time_ist", "")
                if not publish_date or not publish_time:
                    print(f"Skipping {video['name']}: scheduled date/time is missing")
                    continue
                try:
                    result = upload_scheduled(
                        str(video_path),
                        str(metadata_path),
                        publish_date,
                        publish_time,
                        thumbnail_path=str(thumbnail_path),
                    )
                except (RuntimeError, ValueError, OSError) as exc:
                    print(f"Could not retry {video['name']}: {type(exc).__name__}: {exc}")
                    continue
                metadata.update({
                    "upload_status": result["status"],
                    "youtube_video_id": result["video_id"],
                    "youtube_url": result["url"],
                    "publish_at_ist": result["publish_at_ist"],
                })
                metadata_path.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                notes = f"Retried from Drive; scheduled at {result['publish_at_ist']}"
                try:
                    _update_drive_metadata(token, metadata_file["id"], metadata)
                except (drive_fallback.DriveFallbackError, requests.RequestException) as exc:
                    notes += f"; Drive metadata update failed: {type(exc).__name__}: {exc}"
                output = {
                    "date": calendar_date,
                    "slot": slot,
                    "status": "scheduled",
                    "youtube_video_id": result["video_id"],
                    "drive_link": video.get("webViewLink", ""),
                    "notes": notes,
                }
                _write_result(result_dir, output)
                retried.append(output)
                print(f"Scheduled {video['name']}: {result['url']}")
    return retried


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS_DIR)
    parser.add_argument("--calendar", type=Path, default=None)
    args = parser.parse_args()
    retried = retry_failed_uploads(args.results)
    print(f"Retried {len(retried)} Drive-saved videos")
    if args.calendar and retried:
        sys.path.insert(0, str(ROOT / "calendar"))
        from update_calendar import merge_results
        merge_results(args.calendar, args.results)


if __name__ == "__main__":
    main()
