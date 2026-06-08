def parse_tag_string(tags: str | None) -> list[str]:
    """Parse comma- or space-separated tag names."""
    if not tags:
        return []
    parts = []
    for chunk in tags.replace(",", " ").split():
        cleaned = chunk.strip().lstrip("#").lower()
        if cleaned:
            parts.append(cleaned)
    return list(dict.fromkeys(parts))
