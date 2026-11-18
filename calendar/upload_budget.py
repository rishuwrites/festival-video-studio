"""Deterministically reserve the daily YouTube upload budget before matrix jobs start."""

import os


def batch_upload_limit(total_limit=None, legacy_count=0):
    """Reserve the legacy upload from the combined daily YouTube API budget."""
    if total_limit is None:
        try:
            total_limit = int(os.getenv("MAX_API_UPLOADS_PER_DAY", "6"))
        except ValueError as exc:
            raise ValueError("MAX_API_UPLOADS_PER_DAY must be a non-negative integer") from exc
    if isinstance(total_limit, bool) or not isinstance(total_limit, int) or total_limit < 0:
        raise ValueError("Upload budget must be a non-negative integer")
    if isinstance(legacy_count, bool) or legacy_count not in (0, 1):
        raise ValueError("Legacy upload count must be zero or one")
    return max(0, total_limit - legacy_count)


def allocate_uploads(rows, limit=None):
    """Return copied rows with at most ``limit`` upload slots reserved in slot order."""
    if limit is None:
        try:
            limit = int(os.getenv("MAX_API_UPLOADS_PER_DAY", "6"))
        except ValueError as exc:
            raise ValueError("MAX_API_UPLOADS_PER_DAY must be a non-negative integer") from exc
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("Upload budget must be a non-negative integer")

    ordered = sorted(rows, key=lambda row: (int(row["slot"]), row["date"]))
    result = []
    for index, row in enumerate(ordered):
        allocated = dict(row)
        allocated["upload_allowed"] = index < limit
        if not allocated["upload_allowed"]:
            allocated["drive_reason"] = "quota_reserved"
        result.append(allocated)
    return result
