import hashlib

import httpx
import jsonschema
import pytest

from forgejo_mcp.application.errors import ExternalServiceUnavailable, ValidationFailed
from forgejo_mcp.audit.redaction import extract_target, redact_arguments
from forgejo_mcp.forgejo.client import (
    DEFAULT_DIFF_WINDOW_BYTES,
    MAX_DIFF_BYTES,
    ForgejoClient,
    split_diff_sections,
)
from forgejo_mcp.tools.registry import get_tool

COMMON = {
    "base_url": "https://git.example.test",
    "token": "pat",
    "verify_tls": True,
    "owner": "patrick",
    "repo": "repo",
}


def section(path: str, *, body_lines: int = 3, old: str | None = None) -> str:
    old_path = old or path
    header = f"diff --git a/{old_path} b/{path}\n"
    if old is not None:
        header += f"similarity index 90%\nrename from {old_path}\nrename to {path}\n"
    header += f"--- a/{old_path}\n+++ b/{path}\n@@ -1,{body_lines} +1,{body_lines} @@\n"
    return header + "".join(f"+line {index} of {path}\n" for index in range(body_lines))


THREE_FILES = section("src/a.py") + section("src/b.py") + section("docs/c.md")


def client_for(diff: bytes) -> ForgejoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/pulls/8.diff")
        return httpx.Response(200, content=diff)

    return ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))


def test_split_diff_sections_reproduces_the_diff_in_order() -> None:
    sections = split_diff_sections(THREE_FILES)

    assert [item.paths for item in sections] == [
        {"src/a.py"},
        {"src/b.py"},
        {"docs/c.md"},
    ]
    assert "".join(item.text for item in sections) == THREE_FILES


def test_split_diff_sections_only_breaks_on_newlines() -> None:
    tricky = (
        "diff --git a/x b/x\n+text\x0cdiff --git a/fake b/fake\n+more\u2028diff --git a/y b/y\n"
    )

    sections = split_diff_sections(tricky + section("src/a.py"))

    assert [item.path for item in sections] == ["x", "src/a.py"]
    assert sections[0].text == tricky


def test_split_diff_sections_reads_quoted_and_spaced_headers() -> None:
    quoted = 'diff --git "a/caf\\303\\251 x.txt" "b/caf\\303\\251 x.txt"\n+x\n'
    spaced = "diff --git a/with space.txt b/with space.txt\n+y\n"

    sections = split_diff_sections(quoted + spaced)

    assert "café x.txt" in sections[0].paths
    assert "with space.txt" in sections[1].paths


async def test_paths_select_one_section_of_three() -> None:
    raw = THREE_FILES.encode()
    diff = await client_for(raw).get_pull_request_diff(**COMMON, number=8, paths=["src/b.py"])

    assert diff.content == section("src/b.py")
    assert diff.size == len(section("src/b.py").encode())
    assert diff.total_size == len(raw)
    assert diff.sha256 == hashlib.sha256(raw).hexdigest()
    assert diff.files_included == ["src/b.py"]
    assert diff.files_missing == []
    assert diff.offset == 0
    assert diff.returned_bytes == diff.size
    assert diff.truncated is False
    assert "src/a.py" not in diff.content
    assert "docs/c.md" not in diff.content


@pytest.mark.parametrize("requested", ["old/name.py", "new/name.py"])
async def test_rename_is_found_by_old_or_new_path(requested: str) -> None:
    renamed = section("new/name.py", old="old/name.py")
    raw = (section("src/a.py") + renamed).encode()

    diff = await client_for(raw).get_pull_request_diff(**COMMON, number=8, paths=[requested])

    assert diff.content == renamed
    assert diff.files_included == [requested]
    assert diff.files_missing == []


async def test_missing_paths_are_reported_without_failing() -> None:
    diff = await client_for(THREE_FILES.encode()).get_pull_request_diff(
        **COMMON, number=8, paths=["src/a.py", "nope.txt", "src/a.py"]
    )

    assert diff.content == section("src/a.py")
    assert diff.files_included == ["src/a.py"]
    assert diff.files_missing == ["nope.txt"]


async def test_no_paths_returns_whole_diff_bounded_by_default_window() -> None:
    raw = THREE_FILES.encode()
    diff = await client_for(raw).get_pull_request_diff(**COMMON, number=8)

    assert DEFAULT_DIFF_WINDOW_BYTES == 64 * 1024
    assert diff.content == THREE_FILES
    assert diff.size == diff.total_size == len(raw)
    assert diff.files_included == ["src/a.py", "src/b.py", "docs/c.md"]
    assert diff.files_missing == []
    assert diff.truncated is False

    big_raw = b"diff --git a/big b/big\n" + b"".join(b"+" + b"y" * 1000 + b"\n" for _ in range(80))
    assert len(big_raw) > DEFAULT_DIFF_WINDOW_BYTES
    windowed = await client_for(big_raw).get_pull_request_diff(**COMMON, number=8)

    assert windowed.truncated is True
    assert windowed.returned_bytes <= DEFAULT_DIFF_WINDOW_BYTES
    assert windowed.content.endswith("\n")
    assert windowed.total_size == windowed.size == len(big_raw)


async def test_max_bytes_truncates_on_a_line_boundary() -> None:
    raw = THREE_FILES.encode()
    lines = raw.split(b"\n")
    cut = len(lines[0]) + 1 + len(lines[1]) + 1 + 5  # five bytes into the third line

    diff = await client_for(raw).get_pull_request_diff(**COMMON, number=8, max_bytes=cut)

    assert diff.truncated is True
    assert diff.content == (lines[0] + b"\n" + lines[1] + b"\n").decode()
    assert diff.returned_bytes == len(diff.content.encode())
    assert diff.returned_bytes < cut
    assert diff.size == len(raw)


async def test_offset_continues_from_the_previous_window() -> None:
    raw = THREE_FILES.encode()
    client = client_for(raw)
    first = await client.get_pull_request_diff(**COMMON, number=8, max_bytes=100)
    second = await client.get_pull_request_diff(
        **COMMON, number=8, max_bytes=100, offset=first.offset + first.returned_bytes
    )

    assert first.truncated is True
    assert second.offset == first.returned_bytes
    assert (first.content + second.content).encode() == raw[: second.offset + second.returned_bytes]

    remaining = await client.get_pull_request_diff(
        **COMMON, number=8, max_bytes=MAX_DIFF_BYTES, offset=second.offset
    )
    assert remaining.truncated is False
    assert (first.content + remaining.content).encode() == raw

    beyond = await client.get_pull_request_diff(**COMMON, number=8, offset=len(raw) + 10)
    assert beyond.content == ""
    assert beyond.returned_bytes == 0
    assert beyond.truncated is False


async def test_window_never_splits_a_multibyte_character() -> None:
    raw = ("+" + "\u00e9" * 200 + "\n").encode()  # one line, no newline inside the window

    diff = await client_for(raw).get_pull_request_diff(**COMMON, number=8, max_bytes=42)

    assert diff.truncated is True
    assert diff.returned_bytes == 41  # "+" plus twenty two-byte characters
    assert diff.content.encode() == raw[:41]

    with pytest.raises(ValidationFailed, match="offset"):
        await client_for(raw).get_pull_request_diff(**COMMON, number=8, offset=22)


async def test_input_bound_is_unchanged_and_applies_before_filtering() -> None:
    oversized = client_for(b"x" * (MAX_DIFF_BYTES + 1))

    with pytest.raises(ExternalServiceUnavailable, match="too large"):
        await oversized.get_pull_request_diff(**COMMON, number=8, paths=["a"], max_bytes=1)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"paths": []}, "paths"),
        ({"paths": ["a"] * 51}, "paths"),
        ({"paths": ["../etc"]}, "path is invalid"),
        ({"paths": ["/abs"]}, "path is invalid"),
        ({"max_bytes": 0}, "max_bytes"),
        ({"max_bytes": MAX_DIFF_BYTES + 1}, "max_bytes"),
        ({"offset": -1}, "offset"),
    ],
)
async def test_client_revalidates_window_arguments(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationFailed, match=message):
        await client_for(THREE_FILES.encode()).get_pull_request_diff(**COMMON, number=8, **kwargs)


def test_diff_tool_schema_bounds_the_window() -> None:
    tool = get_tool("forgejo_get_pull_request_diff")
    assert tool is not None
    assert get_tool("forgejo_get_pull_request_files") is not None
    assert "forgejo_get_pull_request_files" in tool.description
    validator = jsonschema.Draft202012Validator(tool.input_schema)
    base = {"owner": "owner", "repo": "repo", "number": 8}

    assert not list(validator.iter_errors(base))
    assert not list(
        validator.iter_errors(
            {**base, "paths": ["src/a.py", "docs/c.md"], "max_bytes": 1024, "offset": 0}
        )
    )
    assert tool.input_schema["properties"]["max_bytes"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": MAX_DIFF_BYTES,
        "default": DEFAULT_DIFF_WINDOW_BYTES,
    }
    for invalid in (
        {**base, "paths": []},
        {**base, "paths": ["a"] * 51},
        {**base, "paths": ["src/../secret"]},
        {**base, "paths": [".."]},
        {**base, "paths": ["/abs"]},
        {**base, "paths": "src/a.py"},
        {**base, "max_bytes": 0},
        {**base, "max_bytes": MAX_DIFF_BYTES + 1},
        {**base, "offset": -1},
        {**base, "unknown": True},
    ):
        assert list(validator.iter_errors(invalid)), invalid

    output = jsonschema.Draft202012Validator(tool.output_schema)
    assert not list(
        output.iter_errors(
            {
                "number": 8,
                "format": "diff",
                "size": 3,
                "total_size": 10,
                "offset": 0,
                "returned_bytes": 3,
                "truncated": True,
                "files_included": ["src/a.py"],
                "files_missing": [],
                "sha256": "0" * 64,
                "content": "abc",
            }
        )
    )


def test_audit_helpers_accept_window_arguments() -> None:
    long_path = "p" * 5000
    arguments = {
        "owner": "patrick",
        "repo": "repo",
        "number": 8,
        "paths": ["src/a.py", long_path],
        "max_bytes": 1024,
        "offset": 0,
    }

    target = extract_target(arguments)
    assert target == {"owner": "patrick", "repo": "repo", "number": 8}

    redacted = redact_arguments(arguments)
    assert redacted.truncated is True
    assert redacted.value["paths"][0] == "src/a.py"
    assert redacted.value["paths"][1].endswith("…[TRUNCATED]")
    assert len(redacted.value["paths"][1]) < len(long_path)
    assert redacted.value["max_bytes"] == 1024
    assert redacted.value["offset"] == 0
