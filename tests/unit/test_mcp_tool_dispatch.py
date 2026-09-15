import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from forgejo_mcp.mcp.server import _execute_tool

_USER = uuid.uuid4()
_REPO = {"owner": "patrick", "repo": "repo"}


async def _dispatch(name: str, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tools = SimpleNamespace(**{method: AsyncMock(return_value={"ok": True})})
    result = await _execute_tool(
        tools,  # type: ignore[arg-type]
        user_id=_USER,
        name=name,
        arguments={**_REPO, **arguments},
        audit_event_id="evt",
    )
    assert result == {"ok": True}
    mock: AsyncMock = getattr(tools, method)
    mock.assert_awaited_once()
    return dict(mock.await_args.kwargs)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, "none"),
        ({"filter": "none"}, "none"),
        ({"filter": "ci"}, "ci"),
    ],
)
async def test_job_log_dispatch_forwards_filter_as_log_filter(
    arguments: dict[str, Any], expected: str
) -> None:
    kwargs = await _dispatch(
        "forgejo_get_action_job_log", "get_action_job_log", {"job_id": 51, **arguments}
    )

    assert kwargs["log_filter"] == expected
    assert "filter" not in kwargs
    assert kwargs["job_id"] == 51
    assert kwargs["max_bytes"] == 64 * 1024
    assert kwargs["from_end"] is True
    assert kwargs["offset"] == 0
    assert kwargs["grep"] is None


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, "none"),
        ({"include_content": True, "filter": "ci"}, "ci"),
    ],
)
async def test_run_logs_dispatch_forwards_filter_as_log_filter(
    arguments: dict[str, Any], expected: str
) -> None:
    kwargs = await _dispatch(
        "forgejo_get_action_run_logs", "get_action_run_logs", {"run_id": 42, **arguments}
    )

    assert kwargs["log_filter"] == expected
    assert "filter" not in kwargs
    assert kwargs["run_id"] == 42
    assert kwargs["include_content"] is arguments.get("include_content", False)
    assert kwargs["max_bytes_per_file"] == 64 * 1024
