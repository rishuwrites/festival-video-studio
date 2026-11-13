import datetime as dt
import json
import os
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from festival_sources import oauth_access_token


YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
TIMEZONE = ZoneInfo("Asia/Kolkata")
CHUNK_SIZE = 8 * 1024 * 1024
MAX_TAG_LENGTH = 30
MAX_TAG_COUNT = 20
MAX_TAG_TOTAL_LENGTH = 500


def scheduled_datetime(publish_date, publish_time, now=None):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publish_date) or not re.fullmatch(
        r"\d{2}:\d{2}", publish_time,
    ):
        raise ValueError("Publish date/time must use YYYY-MM-DD and 24-hour HH:MM (IST)")
    try:
        local_time = dt.datetime.strptime(
            f"{publish_date} {publish_time}", "%Y-%m-%d %H:%M",
        ).replace(tzinfo=TIMEZONE)
    except ValueError as exc:
        raise ValueError("Publish date/time must use YYYY-MM-DD and 24-hour HH:MM (IST)") from exc
    current = now or dt.datetime.now(TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TIMEZONE)
    if local_time <= current + dt.timedelta(minutes=15):
        raise ValueError("Scheduled publish time must be at least 15 minutes in the future (IST)")
    return local_time


def normalize_youtube_tags(values):
    tags = []
    seen = set()
    total_length = 0
    for value in values:
        tag = " ".join(str(value).replace(",", " ").split()).strip(" ,")
        if len(tag) > MAX_TAG_LENGTH:
            if ":" in tag:
                tag = tag.split(":", 1)[0].strip()
        if len(tag) > MAX_TAG_LENGTH:
            shortened = []
            for word in tag.split():
                candidate = " ".join((*shortened, word))
                if len(candidate) > MAX_TAG_LENGTH:
                    break
                shortened.append(word)
            tag = " ".join(shortened) or tag[:MAX_TAG_LENGTH]
        tag = tag.rstrip(" ,:-")
        key = tag.casefold()
        separator_length = 1 if tags else 0
        if (not tag or key in seen or len(tags) >= MAX_TAG_COUNT
                or total_length + separator_length + len(tag) > MAX_TAG_TOTAL_LENGTH):
            continue
        tags.append(tag)
        seen.add(key)
        total_length += separator_length + len(tag)
    return tags


def _check_response(response, operation):
    if response.status_code in (200, 201, 308):
        return
    detail = ""
    try:
        body = response.json()
        errors = body.get("error", {}).get("errors", [])
        detail = errors[0].get("reason", "") if errors else body.get("error", {}).get("message", "")
    except (ValueError, AttributeError, IndexError, TypeError):
        detail = ""
    if response.status_code in (401, 403):
        raise RuntimeError(
            f"YouTube {operation} failed (HTTP {response.status_code}, {detail or 'authorization denied'}). "
            "The OAuth token must have youtube.upload and youtube.readonly scopes, "
            "and YouTube Data API v3 must be enabled."
        )
    raise RuntimeError(f"YouTube {operation} failed (HTTP {response.status_code}, {detail or 'API error'})")


def _existing_upload(access_token, title):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(
            f"{YOUTUBE_API}/channels",
            headers=headers,
            params={"part": "contentDetails", "mine": "true"},
            timeout=30,
        )
        _check_response(response, "channel lookup")
        channels = response.json().get("items", [])
        if not channels:
            raise RuntimeError("YouTube OAuth account has no accessible channel")
        playlist_id = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        page_token = ""
        for _ in range(3):
            params = {"part": "snippet", "playlistId": playlist_id, "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(
                f"{YOUTUBE_API}/playlistItems",
                headers=headers,
                params=params,
                timeout=30,
            )
            _check_response(response, "duplicate check")
            data = response.json()
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                if snippet.get("title") == title:
                    return snippet.get("resourceId", {}).get("videoId")
            page_token = data.get("nextPageToken", "")
            if not page_token:
                break
    except requests.RequestException as exc:
        raise RuntimeError(f"YouTube duplicate check failed: {type(exc).__name__}") from exc
    return None


def _initiate_upload(access_token, metadata, video_size):
    try:
        response = requests.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(video_size),
            },
            json=metadata,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not start YouTube upload: {type(exc).__name__}") from exc
    if response.status_code not in (200, 201):
        _check_response(response, "upload initialization")
    upload_url = response.headers.get("Location", "")
    parsed = urlparse(upload_url)
    if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
        raise RuntimeError("YouTube returned an invalid resumable upload URL")
    return upload_url


def _upload_chunks(upload_url, access_token, video_path):
    size = os.path.getsize(video_path)
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "video/mp4"}
    offset = 0
    try:
        with open(video_path, "rb") as video:
            while offset < size:
                video.seek(offset)
                chunk = video.read(min(CHUNK_SIZE, size - offset))
                end = offset + len(chunk) - 1
                response = requests.put(
                    upload_url,
                    headers={
                        **headers,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    },
                    data=chunk,
                    timeout=(30, 600),
                )
                if response.status_code in (200, 201):
                    return response.json()
                _check_response(response, "video upload")
                received_range = response.headers.get("Range", "")
                if not received_range.startswith("bytes=0-"):
                    raise RuntimeError("YouTube returned an invalid resumable upload range")
                next_offset = int(received_range.removeprefix("bytes=0-")) + 1
                if next_offset <= offset or next_offset > size:
                    raise RuntimeError("YouTube returned an invalid upload offset")
                offset = next_offset
    except requests.RequestException as exc:
        raise RuntimeError(
            "YouTube upload connection failed. Check YouTube Studio before retrying; "
            "the remote upload may have completed."
        ) from exc
    raise RuntimeError("YouTube ended the upload without returning a video ID")


def upload_scheduled(video_path, metadata_path, publish_date, publish_time, now=None):
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Generated video file does not exist: {video_path}")
    publish_at = scheduled_datetime(publish_date, publish_time, now=now)
    with open(metadata_path, "r", encoding="utf-8") as file:
        details = json.load(file)
    title = str(details.get("title", "")).strip()
    description = str(details.get("description", "")).strip()
    tags = normalize_youtube_tags(details.get("tags", []))
    if not title or not description:
        raise ValueError("Video metadata must include a title and description before upload")
    if len(title) > 100:
        raise ValueError("YouTube video title must be 100 characters or fewer")
    if len(description) > 5000:
        raise ValueError("YouTube video description must be 5,000 characters or fewer")
    access_token = oauth_access_token()
    existing_id = _existing_upload(access_token, title)
    if existing_id:
        raise RuntimeError(
            f"A video with this title already exists on the channel: "
            f"https://www.youtube.com/watch?v={existing_id}. Not uploading a duplicate."
        )

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags[:20],
            "categoryId": "27",
            "defaultLanguage": "hi",
            "defaultAudioLanguage": "hi",
        },
        "status": {
            # YouTube requires scheduled uploads to be private; it makes them public at publishAt.
            "privacyStatus": "private",
            "publishAt": publish_at.isoformat(timespec="seconds"),
            "selfDeclaredMadeForKids": False,
        },
    }
    upload_url = _initiate_upload(access_token, metadata, os.path.getsize(video_path))
    result = _upload_chunks(upload_url, access_token, video_path)
    video_id = result.get("id")
    if not video_id:
        raise RuntimeError("YouTube accepted the upload but returned no video ID; verify YouTube Studio")
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "publish_at_ist": publish_at.strftime("%Y-%m-%d %H:%M %Z"),
        "status": "scheduled_public",
    }
