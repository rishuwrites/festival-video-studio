import datetime as dt
import os
import re
import time

import requests

from youtube_upload import scheduled_datetime


GRAPH_API = "https://graph.facebook.com"
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


def _get_offset(session_id, user_token, version):
    response = requests.get(
        f"{GRAPH_API}/{version}/{session_id}",
        headers={"Authorization": f"OAuth {user_token}"},
        timeout=(15, 60),
    )
    payload = _response_body(response, (user_token,), "upload status lookup")
    try:
        offset = int(payload["file_offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FacebookPublishError("Facebook upload status omitted a valid file offset") from exc
    return offset


def _upload_file(session_id, video_path, user_token, version, size):
    offset = 0
    for attempt in range(4):
        try:
            with open(video_path, "rb") as video:
                video.seek(offset)
                response = requests.post(
                    f"{GRAPH_API}/{version}/{session_id}",
                    headers={
                        "Authorization": f"OAuth {user_token}",
                        "file_offset": str(offset),
                        "Content-Type": "application/octet-stream",
                    },
                    data=video,
                    timeout=(30, 1800),
                )
            payload = _response_body(response, (user_token,), "file upload")
            handle = payload.get("h")
            if not isinstance(handle, str) or not handle:
                raise FacebookPublishError("Facebook upload completed without a video handle")
            return handle
        except (FacebookPublishError, requests.Timeout, requests.ConnectionError) as exc:
            if isinstance(exc, FacebookPublishError) and exc.args and "HTTP " in exc.args[0]:
                match = re.search(r"\(HTTP (\d+)\)", exc.args[0])
                if match and int(match.group(1)) not in (408, 429) and int(match.group(1)) < 500:
                    raise
            try:
                offset = _get_offset(session_id, user_token, version)
            except (FacebookPublishError, requests.Timeout, requests.ConnectionError) as status_error:
                if attempt == 3:
                    raise FacebookPublishError(
                        "Could not verify Facebook upload progress after a network error",
                        uncertain=True,
                    ) from status_error
                time.sleep(2 ** attempt)
                continue
            if offset >= size:
                raise FacebookPublishError(
                    "Facebook received the full video but did not return its handle",
                    uncertain=True,
                ) from exc
            if not 0 <= offset < size:
                raise FacebookPublishError("Facebook returned an invalid upload offset") from exc
            if attempt == 3:
                raise FacebookPublishError(
                    f"Facebook upload did not complete; verified offset {offset} of {size}",
                ) from exc
            time.sleep(2 ** attempt)
    raise FacebookPublishError("Facebook resumable upload exhausted its retries")


def upload_scheduled(video_path, title, description, publish_date, publish_time, now=None):
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    page_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    app_id = os.getenv("META_APP_ID", "").strip()
    user_token = os.getenv("META_USER_ACCESS_TOKEN", "").strip()
    version = os.getenv("META_GRAPH_API_VERSION") or GRAPH_API_VERSION
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("META_GRAPH_API_VERSION must use a version such as v27.0")
    missing = [
        name for name, value in (
            ("FACEBOOK_PAGE_ID", page_id),
            ("FACEBOOK_PAGE_ACCESS_TOKEN", page_token),
            ("META_APP_ID", app_id),
            ("META_USER_ACCESS_TOKEN", user_token),
        ) if not value
    ]
    if missing:
        raise FacebookPublishError(
            "Facebook upload requires repository configuration: " + ", ".join(missing),
        )
    if not os.path.isfile(video_path) or os.path.getsize(video_path) == 0:
        raise FileNotFoundError(f"Facebook video file is missing or empty: {video_path}")
    publish_at = scheduled_datetime(publish_date, publish_time, now=now)
    current = now or dt.datetime.now(publish_at.tzinfo)
    if current.tzinfo is None:
        current = current.replace(tzinfo=publish_at.tzinfo)
    if publish_at > current + dt.timedelta(days=180):
        raise ValueError("Facebook scheduled publish time must be within 180 days")

    size = os.path.getsize(video_path)
    secrets = (page_token, user_token)
    try:
        response = requests.post(
            f"{GRAPH_API}/{version}/{app_id}/uploads",
            params={
                "file_name": os.path.basename(video_path),
                "file_length": str(size),
                "file_type": "video/mp4",
                "access_token": user_token,
            },
            timeout=(15, 60),
        )
    except requests.RequestException as exc:
        raise FacebookPublishError(
            "Facebook upload-session creation failed; verify Page uploads before retrying",
            uncertain=True,
        ) from exc
    payload = _response_body(response, secrets, "upload-session creation")
    session_id = payload.get("id")
    if not isinstance(session_id, str) or not session_id.startswith("upload:"):
        raise FacebookPublishError("Meta did not return a valid resumable upload session")

    handle = _upload_file(session_id, video_path, user_token, version, size)
    try:
        response = requests.post(
            f"{VIDEO_GRAPH_API}/{version}/{page_id}/videos",
            data={
                "access_token": page_token,
                "title": title,
                "description": description,
                "fbuploader_video_file_chunk": handle,
                "published": "false",
                "scheduled_publish_time": str(int(publish_at.timestamp())),
            },
            timeout=(15, 180),
        )
    except requests.RequestException as exc:
        raise FacebookPublishError(
            "Facebook publish request failed; check the Page for an existing scheduled video before retrying",
            uncertain=True,
        ) from exc
    payload = _response_body(
        response, secrets, "scheduled publish", uncertain_on_server_error=True,
    )
    video_id = payload.get("id")
    if not video_id:
        raise FacebookPublishError(
            "Facebook accepted the request without returning a video ID; check the Page before retrying",
            uncertain=True,
        )
    return {
        "video_id": str(video_id),
        "url": f"https://www.facebook.com/{page_id}/videos/{video_id}",
        "publish_at_ist": publish_at.strftime("%Y-%m-%d %H:%M %Z"),
        "status": "scheduled_public",
    }
