"""Save generated videos to Drive when YouTube upload is unavailable."""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests

from festival_sources import oauth_access_token


DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
CHUNK_SIZE = 8 * 1024 * 1024
ROOT_FOLDER_NAME = "ParvKatha_Failed_Uploads"


class DriveFallbackError(RuntimeError):
    pass


def _check(response, operation):
    if response.status_code in (200, 201, 308):
        return
    try:
        detail = response.json().get("error", {}).get("message", "")
    except (ValueError, AttributeError):
        detail = ""
    if response.status_code in (401, 403):
        raise DriveFallbackError(
            f"Google Drive {operation} failed (HTTP {response.status_code}). "
            "The YT_REFRESH_TOKEN must be regenerated with the drive.file scope; "
            "enable the Google Drive API in the same Cloud project."
        )
    raise DriveFallbackError(
        f"Google Drive {operation} failed (HTTP {response.status_code}: {detail or 'API error'})"
    )


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _find_folder(token, name, parent_id=None):
    escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
    clauses = [
        "mimeType='application/vnd.google-apps.folder'",
        f"name='{escaped_name}'",
        "trashed=false",
    ]
    if parent_id:
        clauses.append(f"'{parent_id}' in parents")
    response = requests.get(
        f"{DRIVE_API}/files",
        headers=_headers(token),
        params={"q": " and ".join(clauses), "fields": "files(id,name,webViewLink)", "pageSize": 100},
        timeout=30,
    )
    _check(response, "folder lookup")
    folders = response.json().get("files", [])
    if folders:
        return folders[0]
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    response = requests.post(
        f"{DRIVE_API}/files",
        headers={**_headers(token), "Content-Type": "application/json"},
        params={"fields": "id,name,webViewLink"},
        json=metadata,
        timeout=30,
    )
    _check(response, "folder creation")
    folder = response.json()
    if not folder.get("id"):
        raise DriveFallbackError("Google Drive created a folder without returning an ID")
    return folder


def _find_file(token, folder_id, name):
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    response = requests.get(
        f"{DRIVE_API}/files",
        headers=_headers(token),
        params={
            "q": f"'{folder_id}' in parents and name='{escaped}' and trashed=false",
            "fields": "files(id,name,webViewLink)",
            "pageSize": 100,
        },
        timeout=30,
    )
    _check(response, "file lookup")
    files = response.json().get("files", [])
    return files[0] if files else None


def _upload_resumable(token, path, folder_id, upload_name=None):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Drive fallback file does not exist: {path}")
    upload_name = upload_name or path.name
    existing = _find_file(token, folder_id, upload_name)
    if existing:
        return existing
    content_type = "video/mp4" if path.suffix.casefold() == ".mp4" else (
        "image/jpeg" if path.suffix.casefold() in {".jpg", ".jpeg"} else "application/json"
    )
    metadata = {"name": upload_name, "parents": [folder_id]}
    try:
        response = requests.post(
            DRIVE_UPLOAD,
            headers={
                **_headers(token),
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": content_type,
                "X-Upload-Content-Length": str(path.stat().st_size),
            },
            params={"uploadType": "resumable", "fields": "id,name,webViewLink"},
            json=metadata,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise DriveFallbackError(f"Could not start Drive upload: {type(exc).__name__}") from exc
    if response.status_code not in (200, 201):
        _check(response, "upload initialization")
    upload_url = response.headers.get("Location", "")
    parsed = urlparse(upload_url)
    if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
        raise DriveFallbackError("Google Drive returned an invalid resumable upload URL")

    size = path.stat().st_size
    offset = 0
    try:
        with path.open("rb") as file:
            while offset < size:
                file.seek(offset)
                chunk = file.read(min(CHUNK_SIZE, size - offset))
                end = offset + len(chunk) - 1
                response = requests.put(
                    upload_url,
                    headers={
                        "Content-Type": content_type,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    },
                    data=chunk,
                    timeout=(30, 600),
                )
                if response.status_code in (200, 201):
                    result = response.json()
                    if not result.get("id"):
                        raise DriveFallbackError("Google Drive accepted the upload without returning an ID")
                    return result
                _check(response, "resumable upload")
                received_range = response.headers.get("Range", "")
                if not received_range.startswith("bytes=0-"):
                    raise DriveFallbackError("Google Drive returned an invalid resumable upload range")
                next_offset = int(received_range.removeprefix("bytes=0-")) + 1
                if next_offset <= offset or next_offset > size:
                    raise DriveFallbackError("Google Drive returned an invalid upload offset")
                offset = next_offset
    except requests.RequestException as exc:
        raise DriveFallbackError(f"Drive upload connection failed: {type(exc).__name__}") from exc
    raise DriveFallbackError("Google Drive ended the upload without returning a file ID")


def save_to_drive(video_path, thumbnail_path, metadata_path, slot, reason,
                  publish_date="", publish_time="", calendar_date=""):
    for path in (video_path, thumbnail_path, metadata_path):
        if not path or not Path(path).is_file():
            raise FileNotFoundError(f"Drive fallback requires an existing video, thumbnail, and metadata: {path}")
    try:
        token = oauth_access_token()
    except RuntimeError as exc:
        raise DriveFallbackError(str(exc)) from exc
    try:
        root = _find_folder(token, ROOT_FOLDER_NAME)
        folder = _find_folder(token, f"{slot}_{reason}", root["id"])

        with Path(metadata_path).open(encoding="utf-8") as file:
            metadata = json.load(file)
        metadata.update({
            "slot": int(slot),
            "publish_date": publish_date,
            "publish_time_ist": publish_time,
            "calendar_date": calendar_date,
            "drive_reason": reason,
        })
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False,
        ) as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
            metadata_upload_path = Path(file.name)
        try:
            uploaded = [
                _upload_resumable(token, video_path, folder["id"]),
                _upload_resumable(token, thumbnail_path, folder["id"]),
                _upload_resumable(
                    token, metadata_upload_path, folder["id"], Path(metadata_path).name,
                ),
            ]
        finally:
            metadata_upload_path.unlink(missing_ok=True)
    except requests.RequestException as exc:
        raise DriveFallbackError(f"Google Drive request failed: {type(exc).__name__}") from exc
    video = uploaded[0]
    return {
        "drive_link": video.get("webViewLink") or f"https://drive.google.com/file/d/{video['id']}/view",
        "folder_id": folder["id"],
        "files": uploaded,
        "reason": reason,
        "status": "failed_saved_to_drive",
    }
