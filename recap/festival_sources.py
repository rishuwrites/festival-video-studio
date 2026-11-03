import os
import re

import requests

import config as S


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
REQUIRED_CHANNELS = 5
MAX_SEARCH_PAGES = 2
MAX_TRANSCRIPT_CHARS = 9000
TRANSCRIPT_LANGUAGES = ["hi", "en"]


def _oauth_access_token():
    client_id = os.getenv("YT_CLIENT_ID", "").strip()
    client_secret = os.getenv("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YT_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError(
            "Set YT_CLIENT_ID, YT_CLIENT_SECRET, and YT_REFRESH_TOKEN, "
            "or provide YT_API_KEY for public YouTube search"
        )

    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not refresh the YouTube OAuth access token: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise RuntimeError(
            f"YouTube OAuth token refresh failed (HTTP {response.status_code}); "
            "check YT_CLIENT_ID, YT_CLIENT_SECRET, and YT_REFRESH_TOKEN"
        )
    try:
        access_token = response.json().get("access_token", "").strip()
    except (ValueError, AttributeError) as exc:
        raise RuntimeError("YouTube OAuth token endpoint returned an invalid response") from exc
    if not access_token:
        raise RuntimeError("YouTube OAuth token endpoint returned no access token")
    return access_token


def oauth_access_token():
    return _oauth_access_token()


def _search_results(api_key, query, access_token=None):
    results = []
    page_token = ""
    for _ in range(MAX_SEARCH_PAGES):
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "relevance",
            "maxResults": 50,
            "regionCode": "IN",
            "relevanceLanguage": "hi",
            "safeSearch": "moderate",
        }
        if api_key:
            params["key"] = api_key
        if page_token:
            params["pageToken"] = page_token
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        try:
            response = requests.get(YOUTUBE_SEARCH_URL, params=params, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = getattr(response, "status_code", None)
            if status == 403 and access_token:
                reason = ""
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        error = body.get("error", {})
                        if isinstance(error, dict):
                            errors = error.get("errors", [])
                            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                                reason = errors[0].get("reason", "")
                            if not reason:
                                reason = error.get("status", "")
                except (ValueError, AttributeError, TypeError):
                    pass
                reason_text = f" ({reason})" if isinstance(reason, str) and reason else ""
                raise RuntimeError(
                    f"YouTube search returned HTTP 403{reason_text}. The OAuth refresh token may lack "
                    "youtube.readonly access, the YouTube Data API v3 may not be enabled, "
                    "or the API quota may be exhausted."
                ) from exc
            raise
        payload = response.json()
        results.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            break
    return results


def _transcript_client():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError(
            "Install the requirements.txt dependencies to retrieve public YouTube captions"
        ) from exc
    return YouTubeTranscriptApi()


def _format_transcript(fetched):
    snippets = getattr(fetched, "snippets", fetched)
    text = " ".join(
        re.sub(r"\s+", " ", str(getattr(snippet, "text", snippet.get("text", "") if isinstance(snippet, dict) else ""))).strip()
        for snippet in snippets
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_transcribed_videos(topic, date="", scope=S.DEFAULT_SCOPE, api_key=None):
    """Find five distinct channels' public Hindi/English captions; never persist transcript text."""
    api_key = api_key or os.getenv("YT_API_KEY")
    access_token = None if api_key else _oauth_access_token()

    queries = [
        " ".join(value for value in (topic, date, "India festival date puja vidhi Hindi") if value),
        " ".join(value for value in (topic, date, "Uttar Pradesh Bihar Purvanchal Bhojpuri Maithili festival rituals") if value),
    ]
    transcript_api = _transcript_client()
    selected = []
    seen_channels = set()
    seen_video_ids = set()
    transcript_errors = []

    for query in queries:
        try:
            results = _search_results(api_key, query, access_token=access_token)
        except RuntimeError as exc:
            raise RuntimeError(f"YouTube source search failed: {exc}") from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", "")
            transcript_errors.append(f"YouTube search failed: {type(exc).__name__} (HTTP {status})")
            continue

        for item in results:
            identifier = item.get("id", {})
            snippet = item.get("snippet", {})
            video_id = identifier.get("videoId")
            channel_id = snippet.get("channelId")
            if not video_id or not channel_id or video_id in seen_video_ids or channel_id in seen_channels:
                continue
            seen_video_ids.add(video_id)
            try:
                transcript = transcript_api.fetch(video_id, languages=TRANSCRIPT_LANGUAGES)
                transcript_text = _format_transcript(transcript)
            except Exception as exc:
                transcript_errors.append(f"{video_id}: {type(exc).__name__}")
                continue
            if not transcript_text:
                transcript_errors.append(f"{video_id}: empty captions")
                continue

            title = str(snippet.get("title") or video_id).strip()
            channel = str(snippet.get("channelTitle") or channel_id).strip()
            language = str(getattr(transcript, "language", "unknown"))
            selected.append({
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "channel_id": channel_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "language": language,
                "transcript_word_count": len(transcript_text.split()),
                "transcript": transcript_text[:MAX_TRANSCRIPT_CHARS],
            })
            seen_channels.add(channel_id)
            print(f"  analyzed public captions: {channel} | {title[:90]}")
            if len(selected) == REQUIRED_CHANNELS:
                return selected

    details = "; ".join(transcript_errors[:5]) or "not enough relevant videos with accessible captions"
    raise RuntimeError(
        f"Need caption transcripts from {REQUIRED_CHANNELS} distinct channels; "
        f"found {len(selected)}. {details}"
    )
