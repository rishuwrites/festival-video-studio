import datetime as dt
import os
import re
from contextlib import nullcontext

import requests

from youtube_upload import scheduled_datetime


VIDEO_GRAPH_API = "https://graph-video.facebook.com"
GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION") or "v27.0"


class FacebookPublishError(RuntimeError):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def _response_body(response, secrets, operation, *, uncertain_on_server_error=False):
    if not 200 <= response.status_code < 300:
        try:
            payload = response.json()
            error = payload.get("error", payload)
            detail = error.get("message") or str(error)
            if error.get("code"):
                detail = f"Meta API error {error['code']}: {detail}"
        except (ValueError, AttributeError):
            detail = response.text[:300] or "invalid response"
        for secret in secrets:
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        raise FacebookPublishError(
            f"Facebook {operation} failed (HTTP {response.status_code}): {detail[:500]}",
            uncertain=uncertain_on_server_error and response.status_code >= 500,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise FacebookPublishError(f"Facebook {operation} returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        detail = "unexpected response" if not isinstance(payload, dict) else str(payload["error"])
        for secret in secrets:
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        raise FacebookPublishError(f"Facebook {operation} failed: {detail[:500]}")
    return payload


def upload_scheduled(
    video_path,
    title,
    description,
    publish_date,
    publish_time,
    now=None,
    thumbnail_path=None,
):
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    page_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    version = os.getenv("META_GRAPH_API_VERSION") or GRAPH_API_VERSION
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("META_GRAPH_API_VERSION must use a version such as v27.0")
    missing = [
        name for name, value in (
            ("FACEBOOK_PAGE_ID", page_id),
            ("FACEBOOK_PAGE_ACCESS_TOKEN", page_token),
        ) if not value
    ]
    if missing:
        raise FacebookPublishError(
            "Facebook upload requires repository configuration: " + ", ".join(missing),
        )
    if not os.path.isfile(video_path) or os.path.getsize(video_path) == 0:
        raise FileNotFoundError(f"Facebook video file is missing or empty: {video_path}")
    if thumbnail_path and (
        not os.path.isfile(thumbnail_path) or os.path.getsize(thumbnail_path) == 0
    ):
        raise FileNotFoundError(f"Facebook thumbnail is missing or empty: {thumbnail_path}")
    publish_at = scheduled_datetime(publish_date, publish_time, now=now)
    current = now or dt.datetime.now(publish_at.tzinfo)
    if current.tzinfo is None:
        current = current.replace(tzinfo=publish_at.tzinfo)
    if publish_at > current + dt.timedelta(days=180):
        raise ValueError("Facebook scheduled publish time must be within 180 days")

    size = os.path.getsize(video_path)
    secrets = (page_token,)
    endpoint = f"{VIDEO_GRAPH_API}/{version}/{page_id}/videos"
    try:
        response = requests.post(
            endpoint,
            data={
                "upload_phase": "start",
                "file_size": str(size),
                "access_token": page_token,
            },
            timeout=(15, 60),
        )
    except requests.RequestException as exc:
        raise FacebookPublishError(
            "Facebook upload start failed; check the Page before retrying",
            uncertain=True,
        ) from exc
    payload = _response_body(response, secrets, "upload start")
    session_id = payload.get("upload_session_id")
    video_id = payload.get("video_id")
    if not isinstance(session_id, str) or not session_id or not video_id:
        raise FacebookPublishError("Meta did not return a valid Page video upload session")
    try:
        start_offset = int(payload.get("start_offset", 0))
        end_offset = int(payload.get("end_offset", size))
    except (TypeError, ValueError) as exc:
        raise FacebookPublishError("Facebook upload start returned invalid file offsets") from exc
    if (
        not 0 <= start_offset <= end_offset <= size
        or (start_offset < size and start_offset == end_offset)
    ):
        raise FacebookPublishError("Facebook upload start returned invalid file offsets")

    with open(video_path, "rb") as video:
        while start_offset < end_offset:
            video.seek(start_offset)
            chunk = video.read(end_offset - start_offset)
            if not chunk:
                raise FacebookPublishError("Facebook upload could not read the next video chunk")
            try:
                response = requests.post(
                    endpoint,
                    data={
                        "upload_phase": "transfer",
                        "upload_session_id": session_id,
                        "start_offset": str(start_offset),
                        "access_token": page_token,
                    },
                    files={
                        "video_file_chunk": (
                            "chunk.mp4",
                            chunk,
                            "application/octet-stream",
                        ),
                    },
                    timeout=(30, 1800),
                )
            except requests.RequestException as exc:
                raise FacebookPublishError(
                    "Facebook video chunk transfer failed; check the Page before retrying",
                    uncertain=True,
                ) from exc
            payload = _response_body(response, secrets, "video chunk transfer")
            try:
                next_start_offset = int(payload.get("start_offset", size))
                next_end_offset = int(payload.get("end_offset", size))
            except (TypeError, ValueError) as exc:
                raise FacebookPublishError(
                    "Facebook chunk transfer returned invalid file offsets",
                ) from exc
            if (
                not start_offset < next_start_offset <= next_end_offset <= size
                or (next_start_offset < size and next_start_offset == next_end_offset)
            ):
                raise FacebookPublishError("Facebook chunk transfer returned invalid file offsets")
            start_offset, end_offset = next_start_offset, next_end_offset

    finish_data = {
        "upload_phase": "finish",
        "upload_session_id": session_id,
        "access_token": page_token,
        "title": title[:250],
        "description": description,
        "published": "false",
        "scheduled_publish_time": str(int(publish_at.timestamp())),
    }
    thumbnail_context = (
        open(thumbnail_path, "rb") if thumbnail_path else nullcontext()
    )
    with thumbnail_context as thumbnail_file:
        finish_files = (
            {
                "thumb": (
                    os.path.basename(thumbnail_path),
                    thumbnail_file,
                    "image/jpeg",
                ),
            }
            if thumbnail_file else None
        )
        try:
            response = requests.post(
                endpoint,
                data=finish_data,
                files=finish_files,
                timeout=(15, 180),
            )
        except requests.RequestException as exc:
            raise FacebookPublishError(
                "Facebook upload finish failed; check the Page for an existing scheduled video before retrying",
                uncertain=True,
            ) from exc
    _response_body(
        response, secrets, "upload finish", uncertain_on_server_error=True,
    )
    return {
        "video_id": str(video_id),
        "url": f"https://www.facebook.com/{page_id}/videos/{video_id}",
        "publish_at_ist": publish_at.strftime("%Y-%m-%d %H:%M %Z"),
        "status": "scheduled_public",
    }
