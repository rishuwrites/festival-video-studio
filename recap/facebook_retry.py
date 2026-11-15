import json
import os
from pathlib import Path

import facebook_upload


def _find_metadata(artifact_dir, expected_video_id):
    matches = []
    for path in artifact_dir.glob("*.json"):
        with path.open(encoding="utf-8") as file:
            metadata = json.load(file)
        if metadata.get("youtube_video_id") == expected_video_id:
            matches.append((path, metadata))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one metadata file for YouTube video {expected_video_id}; "
            f"found {len(matches)}"
        )
    return matches[0]


def main():
    artifact_dir = Path(os.environ["FACEBOOK_RETRY_ARTIFACT_DIR"])
    expected_video_id = os.environ["FACEBOOK_RETRY_YOUTUBE_VIDEO_ID"].strip()
    thumbnail_path = Path(os.environ["FACEBOOK_RETRY_THUMBNAIL_PATH"])
    if not artifact_dir.is_dir():
        raise FileNotFoundError(f"Downloaded video artifact is missing: {artifact_dir}")
    if not thumbnail_path.is_file():
        raise FileNotFoundError(f"Facebook thumbnail is missing: {thumbnail_path}")

    metadata_path, metadata = _find_metadata(artifact_dir, expected_video_id)
    if metadata.get("upload_status") != "scheduled_public":
        raise RuntimeError("The source YouTube video is not marked as scheduled")
    if metadata.get("facebook_video_id"):
        raise RuntimeError(
            f"Facebook video already exists in source metadata: "
            f"{metadata['facebook_video_id']}"
        )

    video_path = artifact_dir / metadata.get("video", "")
    if not video_path.is_file():
        raise FileNotFoundError(f"Source video is missing from artifact: {video_path}")
    title = metadata.get("title", "").strip()
    description = metadata.get("description", "").strip()
    if not title or not description:
        raise RuntimeError("Source metadata is missing the original title or description")

    publish_at = metadata.get("publish_at_ist", "").split()
    if len(publish_at) != 3 or publish_at[2] != "IST":
        raise RuntimeError("Source metadata has an invalid IST publication time")

    result = facebook_upload.upload_scheduled(
        str(video_path),
        title,
        description,
        publish_at[0],
        publish_at[1],
        thumbnail_path=str(thumbnail_path),
    )
    metadata.update({
        "facebook_status": result["status"],
        "facebook_video_id": result["video_id"],
        "facebook_url": result["url"],
        "facebook_publish_at_ist": result["publish_at_ist"],
        "facebook_thumbnail": thumbnail_path.name,
    })
    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)
    print(
        f"Facebook Page video scheduled: {result['url']} "
        f"at {result['publish_at_ist']}"
    )


if __name__ == "__main__":
    main()
