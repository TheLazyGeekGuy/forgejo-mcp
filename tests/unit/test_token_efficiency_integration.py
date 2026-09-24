"""Cross-feature proof that the token-efficiency branches coexist.

Each branch reduced tokens on its own axis: compact JSON serialization, lean list
items, a pull request diff window, and windowed/filtered Action logs. They meet in
two shared places — the ``_execute_tool`` dispatch and the single
``serialize_tool_result`` exit point — and the MCP SDK validates ``structuredContent``
against ``output_schema`` whenever structured output is announced. These tests drive
the real client through a mock transport, dispatch through the real handler, serialize
through the real exit point, and validate the payload against the registry schema, so
a schema that drifts from what a handler returns fails here rather than in a client.
"""

import hashlib
import io
import json
import uuid
import zipfile
from typing import Any

import httpx
import jsonschema
import pytest

from forgejo_mcp.audit.redaction import extract_target, redact_arguments, summarize_result
from forgejo_mcp.forgejo.client import ForgejoClient
from forgejo_mcp.mcp.server import _execute_tool, serialize_tool_result
from forgejo_mcp.tools import get_tool, list_tools

_USER = uuid.uuid4()
_BASE_URL = "https://git.example.test"
_LONG_BODY = "Sombré dans la dette technique. " * 40


class _ServiceProxy:
    """Stand in for ``ForgejoToolService``: inject the connection, keep the real client.

    The service is a thin pass-through that adds ``base_url``/``token``/``verify_tls``
    to every client call, so forwarding here exercises the genuine windowing,
    filtering and field-selection code instead of a stub.
    """

    def __init__(self, client: ForgejoClient) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._client, name)

        async def call(_user_id: uuid.UUID, **kwargs: Any) -> Any:
            return await method(base_url=_BASE_URL, token="pat", verify_tls=True, **kwargs)

        return call


async def _dispatch(
    handler: Any, name: str, arguments: dict[str, Any], *, structured_output: bool = True
) -> tuple[dict[str, Any], str]:
    """Run a tool end to end and return ``(structured_payload, compact_text)``.

    Validates the arguments against ``input_schema`` first — as the server does — then
    the serialized result against ``output_schema``.
    """
    spec = get_tool(name)
    assert spec is not None
    jsonschema.validate(instance=arguments, schema=spec.input_schema)
    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    result = await _execute_tool(
        _ServiceProxy(client),  # type: ignore[arg-type]
        user_id=_USER,
        name=name,
        arguments=arguments,
        audit_event_id="evt",
    )
    serialized = serialize_tool_result(result, structured_output=structured_output)
    # Structured output off returns the content list alone, so the SDK emits no
    # ``structuredContent`` next to an ``outputSchema`` it no longer announces.
    if structured_output:
        content, structured = serialized
    else:
        assert not isinstance(serialized, tuple), "structured output off must not carry a payload"
        content, structured = serialized, None

    assert len(content) == 1
    text = content[0].text  # type: ignore[union-attr]
    assert "\n" not in text, "the exit point must emit single-line compact JSON"
    assert text == json.dumps(result, separators=(",", ":"), ensure_ascii=False)
    assert len(text) < len(json.dumps(result, indent=2)), "compact must beat the SDK default"
    assert json.loads(text) == result
    if structured_output:
        assert structured == result
        jsonschema.validate(instance=structured, schema=spec.output_schema)
    # The schema is the contract the SDK enforces; validate the text payload too so a
    # divergence between the two serializations cannot hide here.
    jsonschema.validate(instance=json.loads(text), schema=spec.output_schema)
    return result, text


def _user_payload() -> dict[str, Any]:
    return {
        "id": 42,
        "login": "patrick",
        "full_name": "Patrick",
        "avatar_url": f"{_BASE_URL}/avatar.png",
    }


def _issue_payload(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": _LONG_BODY,
        "state": "open",
        "html_url": f"{_BASE_URL}/patrick/repo/issues/{number}",
        "user": _user_payload(),
        "assignees": [_user_payload()],
        "labels": [{"id": 1, "name": "feature", "color": "00ff00"}],
        "milestone": {"id": 2, "title": "v1"},
        "comments": 1,
        "created_at": "2026-08-02T12:00:00Z",
        "updated_at": "2026-08-02T13:00:00Z",
        "closed_at": None,
    }


def _issues_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path.endswith("/issues")
    return httpx.Response(200, json=[_issue_payload(n) for n in range(1, 4)])


_LIST_ARGUMENTS: dict[str, Any] = {"owner": "patrick", "repo": "repo"}


def _comment_payload(identifier: int) -> dict[str, Any]:
    return {
        "id": identifier,
        "body": _LONG_BODY,
        "html_url": f"{_BASE_URL}/patrick/repo/issues/7#issuecomment-{identifier}",
        "user": _user_payload(),
        "created_at": "2026-08-02T14:00:00Z",
        "updated_at": "2026-08-02T14:00:00Z",
    }


def _pull_payload(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Pull {number}",
        "body": _LONG_BODY,
        "state": "open",
        "draft": False,
        "mergeable": True,
        "merged": False,
        "html_url": f"{_BASE_URL}/patrick/repo/pulls/{number}",
        "user": _user_payload(),
        "base": {"ref": "main", "sha": "aaa", "repo": {"full_name": "patrick/repo"}},
        "head": {"ref": "feature", "sha": "bbb", "repo": {"full_name": "patrick/repo"}},
        "labels": [],
        "created_at": "2026-08-02T12:00:00Z",
        "updated_at": "2026-08-02T13:00:00Z",
        "closed_at": None,
        "merged_at": None,
        "commits": 2,
        "additions": 12,
        "deletions": 3,
        "changed_files": 4,
    }


def _repository_payload(identifier: int) -> dict[str, Any]:
    return {
        "id": identifier,
        "owner": {"login": "patrick"},
        "name": f"forgejo-mcp-{identifier}",
        "full_name": f"patrick/forgejo-mcp-{identifier}",
        "description": _LONG_BODY,
        "private": True,
        "fork": False,
        "default_branch": "main",
        "archived": False,
        "html_url": f"{_BASE_URL}/patrick/forgejo-mcp-{identifier}",
        "updated_at": "2026-08-02T12:00:00Z",
        "stars_count": 3,
        "forks_count": 1,
        "open_issues_count": 2,
        "permissions": {"admin": True, "pull": True, "push": True},
    }


def _payload_handler(items: list[dict[str, Any]]) -> Any:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=items)

    return handler


# Every list tool whose schema the merge touched, with the truncation flag it carries.
_LEAN_LIST_TOOLS: list[tuple[str, Any, dict[str, Any], str]] = [
    (
        "forgejo_list_repositories",
        _payload_handler([_repository_payload(n) for n in range(1, 4)]),
        {},
        "description_truncated",
    ),
    ("forgejo_list_issues", _issues_handler, dict(_LIST_ARGUMENTS), "body_truncated"),
    (
        "forgejo_list_issue_comments",
        _payload_handler([_comment_payload(n) for n in range(1, 4)]),
        {**_LIST_ARGUMENTS, "number": 7},
        "body_truncated",
    ),
    (
        "forgejo_list_pull_requests",
        _payload_handler([_pull_payload(n) for n in range(1, 4)]),
        dict(_LIST_ARGUMENTS),
        "body_truncated",
    ),
]


@pytest.mark.parametrize(("name", "handler", "arguments", "flag"), _LEAN_LIST_TOOLS)
@pytest.mark.parametrize("fields", ["compact", "full"])
async def test_every_lean_list_tool_validates_its_schema_when_serialized(
    name: str, handler: Any, arguments: dict[str, Any], flag: str, fields: str
) -> None:
    """The four list tools the merge reshaped must still match their output schema.

    ``additionalProperties: false`` makes this a two-sided check: a field the handler
    stopped returning and a field it started returning both fail here.
    """
    result, _ = await _dispatch(handler, name, {**arguments, "fields": fields})

    # The envelope declares the lossy mode and only the lossy mode: a compact answer
    # says so, a full one spends no byte saying there was nothing to cut.
    assert result.get("fields") == ("compact" if fields == "compact" else None)
    items = result["items"]
    assert len(items) == 3
    for item in items:
        assert item[flag] is (fields == "compact")
        assert ("html_url" in item) is (fields == "full")
        if "user" in item:
            assert ("avatar_url" in item["user"]) is (fields == "full")


@pytest.mark.parametrize("fields", ["compact", "full"])
async def test_lean_list_result_validates_its_schema_after_compact_serialization(
    fields: str,
) -> None:
    result, text = await _dispatch(
        _issues_handler, "forgejo_list_issues", {**_LIST_ARGUMENTS, "fields": fields}
    )

    items = result["items"]
    assert len(items) == 3
    for item in items:
        assert item["body_truncated"] is (fields == "compact")
        assert ("html_url" in item) is (fields == "full")
        assert ("avatar_url" in item["user"]) is (fields == "full")
    if fields == "compact":
        assert all(len(item["body"]) <= 201 for item in items)
    assert '"body_truncated":' in text


async def test_compact_list_is_strictly_smaller_than_the_full_one() -> None:
    _, compact = await _dispatch(
        _issues_handler, "forgejo_list_issues", {**_LIST_ARGUMENTS, "fields": "compact"}
    )
    _, full = await _dispatch(
        _issues_handler, "forgejo_list_issues", {**_LIST_ARGUMENTS, "fields": "full"}
    )

    assert len(compact) < len(full)


def _noisy_log() -> bytes:
    lines = [
        "2026-09-01T10:00:00.000Z \x1b[32mSetting up the runner\x1b[0m",
        "2026-09-01T10:00:01.000Z progress\rprogress\rprogress done",
        "",
        "",
        "2026-09-01T10:00:02.000Z repeated line",
        "2026-09-01T10:00:03.000Z repeated line",
        "2026-09-01T10:00:04.000Z repeated line",
        "2026-09-01T10:00:05.000Z \x1b[31mERROR the build failed\x1b[0m",
    ]
    padding = [f"2026-09-01T09:{index:02d}:00.000Z filler line {index}" for index in range(60)]
    return ("\n".join(padding + lines) + "\n").encode()


def _job_log_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path.endswith("/actions/jobs/51/logs")
    return httpx.Response(200, content=_noisy_log())


async def test_windowed_and_filtered_job_log_validates_its_schema() -> None:
    raw = _noisy_log()
    result, text = await _dispatch(
        _job_log_handler,
        "forgejo_get_action_job_log",
        {**_LIST_ARGUMENTS, "job_id": 51, "max_bytes": 2048, "from_end": True, "filter": "ci"},
    )

    # The window and the digest keep describing the raw log; the filter only rewrites
    # the returned content.
    assert result["size"] == len(raw)
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["returned_bytes"] <= 2048
    assert result["truncated"] is True
    stats = result["filter_stats"]
    assert stats["removed_ansi"] > 0
    assert stats["removed_timestamps"] > 0
    assert stats["collapsed_lines"] > 0
    assert stats["filtered_lines"] < stats["original_lines"]
    assert "\x1b[" not in result["content"]
    assert "[×3]" in result["content"]
    assert "ERROR the build failed" in result["content"]
    assert '"filter_stats":' in text


async def test_unfiltered_job_log_omits_filter_stats_and_still_validates() -> None:
    result, _ = await _dispatch(
        _job_log_handler,
        "forgejo_get_action_job_log",
        {**_LIST_ARGUMENTS, "job_id": 51, "max_bytes": 2048},
    )

    assert "filter_stats" not in result
    assert "\x1b[" in result["content"]


async def test_grep_and_filter_combine_on_the_same_window() -> None:
    result, _ = await _dispatch(
        _job_log_handler,
        "forgejo_get_action_job_log",
        {**_LIST_ARGUMENTS, "job_id": 51, "grep": "error", "filter": "ci"},
    )

    assert "ERROR the build failed" in result["content"]
    assert "filler line" not in result["content"]
    # grep runs before the window and the filter, so it prefixes each kept line with
    # its number; the leading timestamp is then no longer leading and the ``ci``
    # filter leaves it in place. Established behaviour of the stacked branches, kept
    # explicit here because grep and filter had never been exercised together.
    assert result["content"].startswith("68: 2026-09-01T10:00:05")
    assert result["filter_stats"]["removed_timestamps"] == 0
    assert result["filter_stats"]["removed_ansi"] > 0


async def test_grep_reports_the_size_of_the_match_set_it_windows() -> None:
    """``truncated`` on a grep'd log is unreadable without the size it is measured against.

    ``size`` keeps describing the raw log, so a caller comparing ``returned_bytes`` to it
    would call a complete match set truncated. ``filtered_size`` is that missing
    denominator, and it exists only when ``grep`` is set.
    """
    raw = _noisy_log()
    whole, _ = await _dispatch(
        _job_log_handler,
        "forgejo_get_action_job_log",
        {**_LIST_ARGUMENTS, "job_id": 51, "grep": "repeated line"},
    )
    windowed, _ = await _dispatch(
        _job_log_handler,
        "forgejo_get_action_job_log",
        {**_LIST_ARGUMENTS, "job_id": 51, "grep": "repeated line", "max_bytes": 64},
    )
    ungrepped, _ = await _dispatch(
        _job_log_handler,
        "forgejo_get_action_job_log",
        {**_LIST_ARGUMENTS, "job_id": 51, "max_bytes": 64},
    )

    # The match set is a strict subset of the raw log, and smaller than it.
    assert 0 < whole["filtered_size"] < len(raw) == whole["size"]
    assert whole["returned_bytes"] == whole["filtered_size"]
    assert whole["truncated"] is False
    # Windowed: the cut is readable only against ``filtered_size``, never against ``size``.
    assert windowed["filtered_size"] == whole["filtered_size"]
    assert windowed["returned_bytes"] < windowed["filtered_size"]
    assert windowed["truncated"] is True
    # No grep, no denominator to pay for.
    assert "filtered_size" not in ungrepped


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("0_build.txt", _noisy_log().decode())
        archive.writestr("1_test.txt", "2026-09-01T11:00:00.000Z \x1b[33mtests passed\x1b[0m\n")
    return buffer.getvalue()


def _run_logs_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path.endswith("/actions/runs/42/logs")
    return httpx.Response(200, content=_archive())


async def test_run_log_index_and_filtered_content_validate_their_schema() -> None:
    index, _ = await _dispatch(
        _run_logs_handler, "forgejo_get_action_run_logs", {**_LIST_ARGUMENTS, "run_id": 42}
    )

    assert [entry["name"] for entry in index["files"]] == ["0_build.txt", "1_test.txt"]
    assert all("content" not in entry for entry in index["files"]), "index must stay contentless"
    # An index-only answer announces the omission, so contentless never reads as empty.
    assert index["content_included"] is False

    full, text = await _dispatch(
        _run_logs_handler,
        "forgejo_get_action_run_logs",
        {
            **_LIST_ARGUMENTS,
            "run_id": 42,
            "include_content": True,
            "max_bytes_per_file": 1024,
            "filter": "ci",
        },
    )

    build = full["files"][0]
    assert build["sha256"] == index["files"][0]["sha256"], "the digest covers the raw file"
    assert build["returned_bytes"] <= 1024
    assert build["truncated"] is True
    assert "\x1b[" not in build["content"]
    assert build["filter_stats"]["removed_ansi"] > 0
    assert '"filter_stats":' in text
    # The content is there: nothing to announce, no byte spent announcing it.
    assert "content_included" not in full


def _section(path: str, lines: int = 6) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,{lines} +1,{lines} @@\n"
        + "".join(f"+line {index} of {path}\n" for index in range(lines))
    )


_DIFF = _section("src/a.py") + _section("src/b.py") + _section("docs/c.md")


def _diff_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path.endswith("/pulls/8.diff")
    return httpx.Response(200, content=_DIFF.encode())


async def test_windowed_diff_validates_its_schema() -> None:
    result, text = await _dispatch(
        _diff_handler,
        "forgejo_get_pull_request_diff",
        {
            **_LIST_ARGUMENTS,
            "number": 8,
            "paths": ["src/b.py", "missing.py"],
            "max_bytes": 96,
            "offset": 0,
        },
    )

    assert result["files_included"] == ["src/b.py"]
    assert result["files_missing"] == ["missing.py"]
    assert result["total_size"] == len(_DIFF.encode())
    assert result["sha256"] == hashlib.sha256(_DIFF.encode()).hexdigest()
    assert result["returned_bytes"] <= 96
    assert result["truncated"] is True
    assert result["content"].startswith("diff --git a/src/b.py")
    assert '"files_missing":' in text

    tail, _ = await _dispatch(
        _diff_handler,
        "forgejo_get_pull_request_diff",
        {**_LIST_ARGUMENTS, "number": 8, "paths": ["src/b.py"], "offset": result["returned_bytes"]},
    )
    assert tail["offset"] == result["returned_bytes"]
    assert result["content"] + tail["content"] == _section("src/b.py")


async def test_every_windowed_tool_uses_the_single_serialization_exit_point() -> None:
    """Structured output off must drop ``structuredContent`` for the new tools too."""
    for handler, name, arguments in (
        (_issues_handler, "forgejo_list_issues", {**_LIST_ARGUMENTS, "fields": "compact"}),
        (
            _job_log_handler,
            "forgejo_get_action_job_log",
            {**_LIST_ARGUMENTS, "job_id": 51, "filter": "ci"},
        ),
        (
            _run_logs_handler,
            "forgejo_get_action_run_logs",
            {**_LIST_ARGUMENTS, "run_id": 42, "include_content": True, "filter": "ci"},
        ),
        (
            _diff_handler,
            "forgejo_get_pull_request_diff",
            {**_LIST_ARGUMENTS, "number": 8, "paths": ["src/a.py"], "max_bytes": 128},
        ),
    ):
        await _dispatch(handler, name, arguments, structured_output=False)


_NEW_ARGUMENTS: dict[str, Any] = {
    "owner": "patrick",
    "repo": "repo",
    "number": 8,
    "job_id": 51,
    "run_id": 42,
    "fields": "compact",
    "paths": ["src/a.py", "docs/c.md"],
    "max_bytes": 4096,
    "max_bytes_per_file": 2048,
    "offset": 128,
    "from_end": True,
    "grep": "error",
    "filter": "ci",
    "include_content": True,
}


def test_new_arguments_leave_the_audit_target_unchanged() -> None:
    target = extract_target(_NEW_ARGUMENTS)

    assert target == {"owner": "patrick", "repo": "repo", "number": 8, "job_id": 51, "run_id": 42}


def test_new_arguments_survive_redaction_without_loss() -> None:
    redacted = redact_arguments(_NEW_ARGUMENTS)

    assert redacted.truncated is False
    assert redacted.value == _NEW_ARGUMENTS
    assert redacted.value is not _NEW_ARGUMENTS


async def test_audit_summary_reports_the_windowed_sizes() -> None:
    result, _ = await _dispatch(
        _diff_handler,
        "forgejo_get_pull_request_diff",
        {**_LIST_ARGUMENTS, "number": 8, "max_bytes": 96},
    )

    summary, truncated = summarize_result(result)

    assert truncated is True
    assert summary["content_bytes"] == result["returned_bytes"]
    assert "files_missing" in summary["returned_keys"]


def _object_nodes(schema: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    """Every object node of a JSON Schema, with the path that reaches it."""
    found: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(schema, dict):
        return found
    if schema.get("type") == "object" or "properties" in schema:
        found.append((path, schema))
    for key, value in schema.get("properties", {}).items():
        found.extend(_object_nodes(value, f"{path}.{key}"))
    items = schema.get("items")
    if isinstance(items, dict):
        found.extend(_object_nodes(items, f"{path}[]"))
    for keyword in ("anyOf", "oneOf", "allOf"):
        for index, branch in enumerate(schema.get(keyword, [])):
            found.extend(_object_nodes(branch, f"{path}.{keyword}[{index}]"))
    return found


def test_every_schema_object_stays_closed_after_the_merge() -> None:
    """``additionalProperties: false`` is what makes the schemas catch handler drift.

    Validation alone cannot detect a schema that was loosened — a wider schema still
    accepts a valid payload — so this asserts the structure directly, on every nested
    object of every tool, input and output. A typed free-form map (``additionalProperties``
    holding a schema, as ``forgejo_dispatch_workflow.inputs`` does since before the merge)
    is closed by type and allowed; ``true`` or a missing keyword is not.
    """
    open_nodes: list[str] = []
    for spec in list_tools():
        for kind, schema in (("in", spec.input_schema), ("out", spec.output_schema)):
            for path, node in _object_nodes(schema):
                extra = node.get("additionalProperties")
                if extra is not False and not isinstance(extra, dict):
                    open_nodes.append(f"{spec.name}.{kind}{path[1:]}")

    assert open_nodes == []


def test_the_only_open_map_is_the_one_inherited_from_the_base_branch() -> None:
    """Pin the single typed free-form map so a new one cannot slip in unnoticed."""
    typed_maps = {
        f"{spec.name}.{kind}{path[1:]}"
        for spec in list_tools()
        for kind, schema in (("in", spec.input_schema), ("out", spec.output_schema))
        for path, node in _object_nodes(schema)
        if isinstance(node.get("additionalProperties"), dict)
    }

    assert typed_maps == {"forgejo_dispatch_workflow.in.inputs"}


def test_the_registry_still_exposes_every_tool() -> None:
    specs = list_tools()

    assert len(specs) == 50
    assert len({spec.name for spec in specs}) == 50
    assert all(spec.output_schema for spec in specs)


_NEW_PARAMETERS: dict[str, tuple[str, ...]] = {
    "fields": (
        "forgejo_list_repositories",
        "forgejo_list_issues",
        "forgejo_list_issue_comments",
        "forgejo_list_pull_requests",
    ),
    "paths": ("forgejo_get_pull_request_diff",),
    "max_bytes": ("forgejo_get_pull_request_diff", "forgejo_get_action_job_log"),
    "offset": ("forgejo_get_pull_request_diff", "forgejo_get_action_job_log"),
    "from_end": ("forgejo_get_action_job_log",),
    "grep": ("forgejo_get_action_job_log",),
    "filter": ("forgejo_get_action_job_log", "forgejo_get_action_run_logs"),
    "include_content": ("forgejo_get_action_run_logs",),
    "max_bytes_per_file": ("forgejo_get_action_run_logs",),
}


@pytest.mark.parametrize(("parameter", "owners"), sorted(_NEW_PARAMETERS.items()))
def test_each_new_parameter_lands_on_exactly_its_own_tools(
    parameter: str, owners: tuple[str, ...]
) -> None:
    """A merge that dropped a parameter, or grafted it onto the wrong tool, fails here."""
    carriers = {spec.name for spec in list_tools() if parameter in spec.input_schema["properties"]}

    assert carriers == set(owners)
