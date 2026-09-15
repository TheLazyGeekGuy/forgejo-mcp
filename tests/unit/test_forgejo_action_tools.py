import hashlib
import io
import zipfile
from typing import Any

import httpx
import pytest

from forgejo_mcp.application.errors import ValidationFailed
from forgejo_mcp.forgejo.client import (
    DEFAULT_ACTION_LOG_WINDOW_BYTES,
    MAX_ACTION_LOG_BYTES,
    ForgejoClient,
)


def action_run_payload() -> dict[str, object]:
    return {
        "id": 42,
        "index_in_repo": 7,
        "title": "CI",
        "event": "push",
        "status": "success",
        "workflow_id": "ci.yml",
        "commit_sha": "abc123",
        "prettyref": "main",
        "html_url": "https://git.example.test/patrick/repo/actions/runs/7",
        "created": "2026-08-18T10:00:00Z",
        "started": "2026-08-18T10:00:01Z",
        "stopped": "2026-08-18T10:01:00Z",
        "updated": "2026-08-18T10:01:00Z",
        "duration": 59,
    }


async def test_list_and_get_action_runs_normalize_v16_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            assert request.url.params.multi_items() == [
                ("page", "2"),
                ("limit", "1"),
                ("event", "push"),
                ("event", "workflow_dispatch"),
                ("status", "success"),
                ("workflow_id", "ci.yml"),
                ("head_sha", "abc123"),
                ("ref", "main"),
                ("run_number", "7"),
            ]
            return httpx.Response(
                200, json={"total_count": 3, "workflow_runs": [action_run_payload()]}
            )
        assert request.url.path.endswith("/actions/runs/42")
        return httpx.Response(200, json=action_run_payload())

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    runs = await client.list_action_runs(
        **common,
        event=["push", "workflow_dispatch"],
        status=["success"],
        workflow_id="ci.yml",
        run_number=7,
        head_sha="abc123",
        ref="main",
        page=2,
        limit=1,
    )
    run = await client.get_action_run(**common, run_id=42)

    assert runs["total_count"] == 3
    assert runs["has_more"] is True
    assert runs["items"][0]["run_number"] == 7
    assert run["head_sha"] == "abc123"
    assert run["completed_at"] == "2026-08-18T10:01:00Z"


async def test_list_action_jobs_and_artifacts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 51,
                        "run_id": 42,
                        "name": "test",
                        "status": "success",
                        "attempt": 1,
                        "runs_on": ["docker"],
                        "needs": [],
                    }
                ],
            )
        assert request.url.path.endswith("/artifacts")
        assert dict(request.url.params) == {"page": "1", "limit": "30", "name": "coverage"}
        return httpx.Response(
            200,
            json=[
                {
                    "id": 61,
                    "run_id": 42,
                    "name": "coverage",
                    "size_in_bytes": 1234,
                    "expired": False,
                    "created_at": "2026-08-18T10:01:00Z",
                    "expires_at": None,
                    "updated_at": "2026-08-18T10:01:00Z",
                    "archive_download_url": "https://git.example.test/artifacts/61.zip",
                }
            ],
        )

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
        "run_id": 42,
    }
    jobs = await client.list_action_run_jobs(**common)
    artifacts = await client.list_action_run_artifacts(**common, name="coverage", page=1, limit=30)

    assert jobs.items[0]["runner_labels"] == ["docker"]
    assert jobs.truncated is False
    assert artifacts.items[0]["size_in_bytes"] == 1234


def _log_client(job_log: bytes, archive_bytes: bytes = b"") -> ForgejoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/actions/jobs/51/logs" in request.url.path:
            assert request.headers["Accept"] == "text/plain"
            return httpx.Response(200, content=job_log)
        assert request.url.path.endswith("/actions/runs/42/logs")
        assert request.headers["Accept"] == "application/zip"
        return httpx.Response(200, content=archive_bytes)

    return ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))


def _archive(files: dict[str, str]) -> bytes:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return archive_buffer.getvalue()


_COMMON = {
    "base_url": "https://git.example.test",
    "token": "pat",
    "verify_tls": True,
    "owner": "patrick",
    "repo": "repo",
}
_LINES = b"".join(b"line-%05d ok\n" % index for index in range(1, 12_001))


async def test_job_log_defaults_to_the_last_64kib_on_a_line_boundary() -> None:
    assert len(_LINES) > DEFAULT_ACTION_LOG_WINDOW_BYTES
    client = _log_client(_LINES)

    job_log = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None)

    content = job_log["content"].encode("utf-8")
    assert job_log["size"] == len(_LINES)
    assert job_log["sha256"] == hashlib.sha256(_LINES).hexdigest()
    assert job_log["truncated"] is True
    assert len(content) == job_log["returned_bytes"] <= DEFAULT_ACTION_LOG_WINDOW_BYTES
    assert content.startswith(b"line-") and content.endswith(b"line-12000 ok\n")
    assert job_log["offset"] == len(_LINES) - len(content)
    assert _LINES[job_log["offset"] :] == content
    assert "ok" in job_log["content"]


async def test_job_log_requests_the_attempt_and_sends_the_window_defaults() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["attempt"] == "2"
        return httpx.Response(200, content=b"ok\n")

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    job_log = await client.get_action_job_log(**_COMMON, job_id=51, attempt=2)

    assert job_log == {
        "job_id": 51,
        "attempt": 2,
        "size": 3,
        "sha256": hashlib.sha256(b"ok\n").hexdigest(),
        "content": "ok\n",
        "offset": 0,
        "returned_bytes": 3,
        "truncated": False,
    }


async def test_job_log_smaller_than_the_window_is_returned_whole() -> None:
    log = b"first\nsecond\nthird\n"
    client = _log_client(log)

    head = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, from_end=False, max_bytes=1024
    )
    tail = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, max_bytes=1024)

    for job_log in (head, tail):
        assert job_log["content"] == log.decode()
        assert job_log["offset"] == 0
        assert job_log["returned_bytes"] == job_log["size"] == len(log)
        assert job_log["truncated"] is False


async def test_job_log_head_window_cuts_on_line_boundaries() -> None:
    log = b"first\nsecond\nthird\nfourth\n"
    client = _log_client(log)

    head = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, from_end=False, max_bytes=16
    )
    shifted = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, from_end=False, offset=2, max_bytes=16
    )
    aligned = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, from_end=False, offset=6, max_bytes=16
    )

    assert head["content"] == "first\nsecond\n"
    assert (head["offset"], head["returned_bytes"], head["truncated"]) == (0, 13, True)
    assert shifted["content"] == "second\nthird\n"
    assert shifted["offset"] == 6
    assert aligned["content"] == "second\nthird\n"
    assert aligned["offset"] == 6


async def test_job_log_tail_window_honours_offset_from_the_end() -> None:
    log = b"first\nsecond\nthird\nfourth\n"
    client = _log_client(log)

    tail = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, max_bytes=10)
    previous = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, max_bytes=10, offset=7
    )
    mid_line = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, max_bytes=16, offset=3
    )

    assert tail["content"] == "fourth\n"
    assert (tail["offset"], tail["returned_bytes"], tail["truncated"]) == (19, 7, True)
    assert previous["content"] == "third\n"
    assert previous["offset"] == 13
    assert mid_line["content"] == "second\nthird\n"
    assert mid_line["offset"] == 6


async def test_job_log_without_newlines_falls_back_to_raw_byte_windows() -> None:
    log = b"x" * 100
    client = _log_client(log)

    tail = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, max_bytes=10)
    head = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, from_end=False, offset=5, max_bytes=10
    )

    assert tail["content"] == "x" * 10
    assert tail["offset"] == 90
    assert head["content"] == "x" * 10
    assert head["offset"] == 5


async def test_job_log_grep_returns_numbered_matching_lines() -> None:
    log = b"step one\nERROR: boom\nstep two\nerror again\ndone\n"
    client = _log_client(log)

    matches = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, grep="error")
    bounded = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, grep="ERROR", max_bytes=16
    )
    none = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, grep="missing")
    disabled = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, grep="")

    assert matches["content"] == "2: ERROR: boom\n4: error again\n"
    assert matches["size"] == len(log)
    assert matches["sha256"] == hashlib.sha256(log).hexdigest()
    assert matches["returned_bytes"] == len(matches["content"])
    assert matches["truncated"] is False
    assert bounded["content"] == "4: error again\n"
    assert bounded["truncated"] is True
    assert bounded["offset"] == len("2: ERROR: boom\n")
    assert none["content"] == ""
    assert none["returned_bytes"] == 0
    assert none["truncated"] is False
    assert disabled["content"] == log.decode()


async def test_job_log_larger_than_one_mib_is_capped_at_max_bytes() -> None:
    oversized_log = b"y" * (MAX_ACTION_LOG_BYTES + 1)
    client = _log_client(oversized_log)

    job_log = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, max_bytes=MAX_ACTION_LOG_BYTES
    )
    default = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None)

    assert job_log["size"] == MAX_ACTION_LOG_BYTES + 1
    assert job_log["returned_bytes"] == len(job_log["content"]) == MAX_ACTION_LOG_BYTES
    assert job_log["truncated"] is True
    assert default["returned_bytes"] == DEFAULT_ACTION_LOG_WINDOW_BYTES


async def test_job_log_invalid_bytes_are_replaced_not_rejected() -> None:
    client = _log_client(b"ok \xff\xfe\n")

    job_log = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None)

    assert job_log["content"] == "ok \ufffd\ufffd\n"


@pytest.mark.parametrize(
    "arguments",
    [
        {"max_bytes": 0},
        {"max_bytes": MAX_ACTION_LOG_BYTES + 1},
        {"max_bytes": True},
        {"offset": -1},
        {"grep": "g" * 257},
    ],
)
async def test_job_log_rejects_out_of_range_window_arguments(arguments: dict[str, Any]) -> None:
    client = _log_client(b"ok\n")

    with pytest.raises(ValidationFailed):
        await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, **arguments)


_NOISY_LOG = (
    b"2026-08-18T10:00:01.000000000Z \x1b[1mSetup\x1b[0m\n"
    b"2026-08-18T10:00:02.000000000Z retry\n"
    b"2026-08-18T10:00:03.000000000Z retry\n"
    b"2026-08-18T10:00:04.000000000Z \x1b[32mdone\x1b[0m\n"
)


async def test_job_log_ci_filter_cleans_the_window_and_reports_its_stats() -> None:
    client = _log_client(_NOISY_LOG)

    filtered = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, log_filter="ci")

    assert filtered["content"] == "Setup\nretry [\u00d72]\ndone\n"
    assert filtered["size"] == len(_NOISY_LOG)
    assert filtered["sha256"] == hashlib.sha256(_NOISY_LOG).hexdigest()
    assert filtered["offset"] == 0
    assert filtered["returned_bytes"] == len(_NOISY_LOG)
    assert filtered["truncated"] is False
    assert filtered["filter_stats"] == {
        "removed_ansi": 4,
        "removed_carriage_returns": 0,
        "removed_timestamps": 4,
        "collapsed_lines": 1,
        "removed_blank_lines": 0,
        "original_lines": 4,
        "filtered_lines": 3,
    }


async def test_job_log_filter_none_is_the_default_and_adds_nothing() -> None:
    client = _log_client(_NOISY_LOG)

    default = await client.get_action_job_log(**_COMMON, job_id=51, attempt=None)
    explicit = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, log_filter="none"
    )

    assert default == explicit
    assert default["content"] == _NOISY_LOG.decode()
    assert "filter_stats" not in default


async def test_job_log_ci_filter_applies_after_the_window_not_before() -> None:
    line = b"2026-08-18T10:00:01.000000000Z msg\n"
    assert len(line) == 35
    log = line * 3
    client = _log_client(log)

    tail = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, max_bytes=40, log_filter="ci"
    )
    head = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, max_bytes=40, from_end=False, log_filter="ci"
    )

    # A 40-byte window holds one raw line; filtering first would have let three 4-byte
    # lines through. offset/returned_bytes/truncated stay defined on the raw bytes.
    assert tail["content"] == "msg\n"
    assert (tail["offset"], tail["returned_bytes"], tail["truncated"]) == (70, 35, True)
    assert tail["filter_stats"]["original_lines"] == 1
    assert head["content"] == "msg\n"
    assert (head["offset"], head["returned_bytes"], head["truncated"]) == (0, 35, True)


async def test_job_log_ci_filter_applies_to_grep_output() -> None:
    client = _log_client(_NOISY_LOG)

    matches = await client.get_action_job_log(
        **_COMMON, job_id=51, attempt=None, grep="retry", log_filter="ci"
    )

    # Line-number prefixes come first, so the strict leading-timestamp rule does not fire
    # and numbered lines never fold; ANSI stripping still applies.
    assert matches["content"] == (
        "2: 2026-08-18T10:00:02.000000000Z retry\n3: 2026-08-18T10:00:03.000000000Z retry\n"
    )
    assert matches["filter_stats"]["removed_timestamps"] == 0
    assert matches["filter_stats"]["collapsed_lines"] == 0


async def test_job_log_rejects_an_unknown_filter() -> None:
    client = _log_client(b"ok\n")

    with pytest.raises(ValidationFailed):
        await client.get_action_job_log(**_COMMON, job_id=51, attempt=None, log_filter="all")


async def test_run_logs_return_an_index_only_by_default() -> None:
    files = {"test-51-attempt-1.log": "tests passed\n", "lint-52-attempt-1.log": "lint passed\n"}
    archive_bytes = _archive(files)
    client = _log_client(b"", archive_bytes)

    run_logs = await client.get_action_run_logs(**_COMMON, run_id=42)

    assert run_logs["run_id"] == 42
    assert run_logs["size"] == len(archive_bytes)
    assert run_logs["sha256"] == hashlib.sha256(archive_bytes).hexdigest()
    assert run_logs["files"] == [
        {
            "name": name,
            "size": len(content),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
        for name, content in files.items()
    ]
    assert run_logs["files_truncated"] is False


async def test_run_logs_include_content_is_bounded_per_file_from_the_end() -> None:
    files = {
        "test-51-attempt-1.log": "setup\ntests passed\nteardown\n",
        "lint-52-attempt-1.log": "lint passed\n",
    }
    client = _log_client(b"", _archive(files))

    run_logs = await client.get_action_run_logs(
        **_COMMON, run_id=42, include_content=True, max_bytes_per_file=12
    )
    whole = await client.get_action_run_logs(**_COMMON, run_id=42, include_content=True)

    test_log, lint_log = run_logs["files"]
    assert test_log["content"] == "teardown\n"
    assert test_log["size"] == len(files["test-51-attempt-1.log"])
    assert (test_log["offset"], test_log["returned_bytes"], test_log["truncated"]) == (19, 9, True)
    assert lint_log["content"] == "lint passed\n"
    assert (lint_log["offset"], lint_log["returned_bytes"], lint_log["truncated"]) == (0, 12, False)
    assert run_logs["files_truncated"] is False
    assert [item["content"] for item in whole["files"]] == list(files.values())
    assert all(item["truncated"] is False for item in whole["files"])


async def test_run_logs_ci_filter_applies_per_file_after_the_window() -> None:
    files = {
        "test-51-attempt-1.log": _NOISY_LOG.decode(),
        "lint-52-attempt-1.log": "\x1b[32mlint passed\x1b[0m\n",
    }
    client = _log_client(b"", _archive(files))

    filtered = await client.get_action_run_logs(
        **_COMMON, run_id=42, include_content=True, log_filter="ci"
    )
    windowed = await client.get_action_run_logs(
        **_COMMON, run_id=42, include_content=True, max_bytes_per_file=48, log_filter="ci"
    )
    index = await client.get_action_run_logs(**_COMMON, run_id=42, log_filter="ci")
    plain = await client.get_action_run_logs(**_COMMON, run_id=42, include_content=True)

    test_log, lint_log = filtered["files"]
    assert test_log["content"] == "Setup\nretry [\u00d72]\ndone\n"
    assert test_log["sha256"] == hashlib.sha256(_NOISY_LOG).hexdigest()
    assert (test_log["size"], test_log["returned_bytes"]) == (len(_NOISY_LOG), len(_NOISY_LOG))
    assert test_log["filter_stats"]["collapsed_lines"] == 1
    assert lint_log["content"] == "lint passed\n"
    assert lint_log["filter_stats"]["removed_ansi"] == 2
    assert windowed["files"][0]["content"] == "done\n"
    last_line = _NOISY_LOG[_NOISY_LOG.rstrip(b"\n").rfind(b"\n") + 1 :]
    assert len(last_line) == 45
    assert windowed["files"][0]["offset"] == len(_NOISY_LOG) - 45
    assert windowed["files"][0]["returned_bytes"] == 45
    assert windowed["files"][0]["truncated"] is True
    assert all("filter_stats" not in item and "content" not in item for item in index["files"])
    assert all("filter_stats" not in item for item in plain["files"])
    assert [item["content"] for item in plain["files"]] == list(files.values())


async def test_run_logs_reject_an_unknown_filter() -> None:
    client = _log_client(b"", _archive({"a.log": "ok\n"}))

    with pytest.raises(ValidationFailed):
        await client.get_action_run_logs(**_COMMON, run_id=42, log_filter="raw")


async def test_run_logs_keep_the_shared_one_mib_budget_and_file_limit() -> None:
    files = {f"job-{index}.log": "x" * 600_000 + "\n" for index in range(3)}
    client = _log_client(b"", _archive(files))

    run_logs = await client.get_action_run_logs(
        **_COMMON, run_id=42, include_content=True, max_bytes_per_file=MAX_ACTION_LOG_BYTES
    )
    index = await client.get_action_run_logs(**_COMMON, run_id=42)

    assert sum(item["returned_bytes"] for item in run_logs["files"]) <= MAX_ACTION_LOG_BYTES
    assert len(run_logs["files"]) == 2
    assert run_logs["files_truncated"] is True
    assert len(index["files"]) == 3
    assert index["files_truncated"] is False


@pytest.mark.parametrize(
    "arguments",
    [{"max_bytes_per_file": 0}, {"max_bytes_per_file": MAX_ACTION_LOG_BYTES + 1}],
)
async def test_run_logs_reject_out_of_range_windows(arguments: dict[str, Any]) -> None:
    client = _log_client(b"", _archive({"a.log": "ok\n"}))

    with pytest.raises(ValidationFailed):
        await client.get_action_run_logs(**_COMMON, run_id=42, include_content=True, **arguments)


async def test_cancel_and_delete_action_run_use_native_routes() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
        "run_id": 42,
    }
    await client.cancel_action_run(**common)
    await client.delete_action_run(**common)

    assert seen == [
        ("POST", "/api/v1/repos/patrick/repo/actions/runs/42/cancel"),
        ("DELETE", "/api/v1/repos/patrick/repo/actions/runs/42"),
    ]
