"""Deterministically reserve the daily YouTube upload budget before matrix jobs start."""

import os


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
