import json
from datetime import UTC, datetime
from typing import Any

import pytest
from mcp.server.lowlevel import Server
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, TextContent, Tool

from forgejo_mcp.config import Settings
from forgejo_mcp.forgejo.models import RepositorySummary
from forgejo_mcp.mcp.server import build_tool_definition, serialize_tool_result
from forgejo_mcp.tools import get_tool, list_tools

CURRENT_USER = {"id": 42, "username": "Patrick"}


def repository_page(count: int = 30) -> dict[str, Any]:
    items = [
        RepositorySummary(
            id=index,
            owner="Patrick",
            name=f"forgejo-mcp-{index}",
            full_name=f"Patrick/forgejo-mcp-{index}",
            description=f"Repository number {index} with a short description",
            private=index % 2 == 0,
            fork=False,
            default_branch="main",
            archived=False,
            html_url=f"https://git.example.test/Patrick/forgejo-mcp-{index}",
            updated_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
            stars_count=index,
            forks_count=0,
            open_issues_count=index % 5,
            permissions={"admin": True, "push": True, "pull": True},
        ).model_dump(mode="json")
        for index in range(1, count + 1)
    ]
    return {"items": items, "page": 1, "limit": count, "has_more": False}


def test_serialized_text_is_compact_json_equal_to_structured() -> None:
    result = {"id": 42, "username": "Pâtrick", "nested": {"values": [1, 2, {"deep": "é"}]}}

    content, structured = serialize_tool_result(result, structured_output=True)

    assert structured is result
    assert len(content) == 1
    text = content[0]
    assert isinstance(text, TextContent)
    assert "\n" not in text.text
    assert "  " not in text.text
    assert ": " not in text.text
    assert ", " not in text.text
    assert "\\u" not in text.text
    assert json.loads(text.text) == structured


def test_compact_text_is_at_least_a_quarter_smaller_than_indented_json() -> None:
    result = repository_page(30)

    content, _ = serialize_tool_result(result, structured_output=True)
    compact = content[0].text
    indented = json.dumps(result, indent=2)

    assert json.loads(compact) == result
    saving = 1 - len(compact) / len(indented)
    assert saving >= 0.25, f"compact={len(compact)} indented={len(indented)} saving={saving:.1%}"


def test_content_only_when_structured_output_disabled() -> None:
    content = serialize_tool_result(CURRENT_USER, structured_output=False)

    assert isinstance(content, list)
    assert json.loads(content[0].text) == CURRENT_USER


def test_tool_definition_omits_output_schema_when_structured_output_disabled() -> None:
    spec = get_tool("forgejo_get_current_user")
    assert spec is not None

    enabled = build_tool_definition(spec, structured_output=True)
    disabled = build_tool_definition(spec, structured_output=False)

    assert enabled.outputSchema == spec.output_schema
    assert disabled.outputSchema is None
    for tool in (enabled, disabled):
        assert tool.name == spec.name
        assert tool.title == spec.title
        assert tool.inputSchema == spec.input_schema
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


def test_every_tool_definition_drops_output_schema_together() -> None:
    tools = [build_tool_definition(spec, structured_output=False) for spec in list_tools()]

    assert tools
    assert all(tool.outputSchema is None for tool in tools)


def test_settings_default_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(environment="test").mcp_structured_output is True
    monkeypatch.setenv("FMCP_MCP_STRUCTURED_OUTPUT", "false")
    assert Settings(environment="test").mcp_structured_output is False


@pytest.mark.parametrize("structured_output", [True, False])
async def test_sdk_call_tool_result_honours_structured_output(structured_output: bool) -> None:
    spec = get_tool("forgejo_get_current_user")
    assert spec is not None
    server: Server[Any, Any] = Server("test")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_tools() -> list[Tool]:
        return [build_tool_definition(spec, structured_output=structured_output)]

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> Any:
        return serialize_tool_result(dict(CURRENT_USER), structured_output=structured_output)

    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=spec.name, arguments={}),
    )
    response = await server.request_handlers[CallToolRequest](request)

    result = response.root
    assert isinstance(result, CallToolResult)
    assert result.isError is False
    assert json.loads(result.content[0].text) == CURRENT_USER  # type: ignore[union-attr]
    if structured_output:
        assert result.structuredContent == CURRENT_USER
    else:
        assert result.structuredContent is None
