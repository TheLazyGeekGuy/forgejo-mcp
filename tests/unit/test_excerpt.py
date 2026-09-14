import pytest

from forgejo_mcp.forgejo.excerpt import EXCERPT_MAX_CHARS, EXCERPT_SUFFIX, excerpt


def test_none_stays_none_and_is_not_truncated() -> None:
    assert excerpt(None) == (None, False)


def test_short_text_is_returned_unchanged() -> None:
    assert excerpt("Ready for review") == ("Ready for review", False)
    exact = "x" * EXCERPT_MAX_CHARS
    assert excerpt(exact) == (exact, False)


def test_long_text_without_boundary_is_cut_at_the_limit() -> None:
    text, truncated = excerpt("x" * 4096)

    assert truncated is True
    assert text == "x" * EXCERPT_MAX_CHARS + EXCERPT_SUFFIX
    assert len(text) == EXCERPT_MAX_CHARS + len(EXCERPT_SUFFIX)


def test_long_text_is_cut_on_a_word_boundary() -> None:
    body = " ".join(f"word{index:03d}" for index in range(100))

    text, truncated = excerpt(body)

    assert truncated is True
    assert text.endswith(EXCERPT_SUFFIX)
    head = text.removesuffix(EXCERPT_SUFFIX)
    assert not head.endswith(" ")
    assert body.startswith(head)
    assert body[len(head)] == " "
    assert len(head) <= EXCERPT_MAX_CHARS


def test_a_line_break_counts_as_a_boundary() -> None:
    first_line = "a" * 150
    body = first_line + "\n" + "b" * 4096

    text, truncated = excerpt(body)

    assert truncated is True
    assert text == first_line + EXCERPT_SUFFIX


def test_boundary_exactly_at_the_limit_keeps_the_whole_head() -> None:
    body = "w" * EXCERPT_MAX_CHARS + " tail"

    assert excerpt(body) == ("w" * EXCERPT_MAX_CHARS + EXCERPT_SUFFIX, True)


def test_very_early_boundary_is_ignored_to_keep_a_useful_excerpt() -> None:
    body = "ab " + "x" * 4096

    text, truncated = excerpt(body)

    assert truncated is True
    assert text == body[:EXCERPT_MAX_CHARS] + EXCERPT_SUFFIX


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_must_be_positive(limit: int) -> None:
    with pytest.raises(ValueError):
        excerpt("text", max_chars=limit)
