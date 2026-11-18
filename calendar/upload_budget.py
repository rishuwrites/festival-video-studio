"""Mark every planned video for a YouTube upload attempt."""


def allocate_uploads(rows):
    """Return copied rows with YouTube attempts enabled for every video."""
    ordered = sorted(rows, key=lambda row: (int(row["slot"]), row["date"]))
    result = []
    for row in ordered:
        allocated = dict(row)
        allocated["upload_allowed"] = True
        result.append(allocated)
    return result
