"""Bounded text excerpts for list tool items.

List tools return many items per call; a full issue or pull request body can weigh
up to 64 KiB each. ``excerpt`` keeps the head of a text within a fixed character
budget so a page of items stays cheap for an MCP client, while ``get_*`` tools keep
returning the complete text.
"""

EXCERPT_MAX_CHARS = 200
EXCERPT_SUFFIX = "…"
_MIN_BOUNDARY_RATIO = 2


def excerpt(text: str | None, *, max_chars: int = EXCERPT_MAX_CHARS) -> tuple[str | None, bool]:
    """Return ``(excerpt, truncated)`` for ``text``.

    ``None`` and texts of at most ``max_chars`` characters are returned unchanged
    with ``truncated=False``. Longer texts are cut to at most ``max_chars``
    characters, preferably on a line or word boundary (only when the boundary keeps
    at least half of the budget), stripped of trailing whitespace, and suffixed with
    ``EXCERPT_SUFFIX``.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if text is None:
        return None, False
    if len(text) <= max_chars:
        return text, False
    head = text[:max_chars]
    if not text[max_chars].isspace():
        boundary = max(head.rfind("\n"), head.rfind(" "))
        if boundary >= max_chars // _MIN_BOUNDARY_RATIO:
            head = head[:boundary]
    return head.rstrip() + EXCERPT_SUFFIX, True
