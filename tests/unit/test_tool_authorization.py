import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jsonschema
import pytest

from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.authorization.tools import ToolAuthorizationContext, authorize_tool
from forgejo_mcp.db.models import CredentialStatus, RecordStatus
from forgejo_mcp.tools import get_tool, list_tools


def allowed_context(**overrides: bool) -> ToolAuthorizationContext:
    values = {
        "token_valid": True,
        "user_enabled": True,
        "global_tool_enabled": True,
        "user_allowed_tool": True,
        "token_has_tool_grant": True,
        "forgejo_credential_configured": True,
    }
    values.update(overrides)
    return ToolAuthorizationContext(**values)


def test_registry_contains_stable_default_disabled_tool_spec() -> None:
    tools = list_tools()

    assert [tool.name for tool in tools] == [
        "forgejo_get_current_user",
        "forgejo_list_repositories",
        "forgejo_get_repository",
        "forgejo_create_organization_repository",
        "forgejo_migrate_repository",
        "forgejo_update_repository",
        "forgejo_sync_mirror",
        "forgejo_list_branches",
        "forgejo_list_commits",
        "forgejo_get_commit",
        "forgejo_compare_refs",
        "forgejo_get_git_tree",
        "forgejo_list_labels",
        "forgejo_list_milestones",
        "forgejo_list_issues",
        "forgejo_get_issue",
        "forgejo_list_issue_comments",
        "forgejo_list_pull_requests",
        "forgejo_get_pull_request",
        "forgejo_list_pull_request_commits",
        "forgejo_get_pull_request_diff",
        "forgejo_get_file_content",
        "forgejo_create_issue",
        "forgejo_update_issue",
        "forgejo_comment_issue",
        "forgejo_create_pull_request",
        "forgejo_update_pull_request",
        "forgejo_list_repository_contents",
        "forgejo_create_branch",
        "forgejo_commit_changes",
        "forgejo_get_pull_request_files",
        "forgejo_request_pull_request_reviewers",
        "forgejo_remove_pull_request_reviewers",
        "forgejo_list_pull_request_reviews",
        "forgejo_get_pull_request_review",
        "forgejo_submit_pull_request_review",
        "forgejo_merge_pull_request",
        "forgejo_get_pull_request_merge_status",
        "forgejo_get_commit_status",
        "forgejo_list_action_runs",
        "forgejo_get_action_run",
        "forgejo_list_action_run_jobs",
        "forgejo_get_action_job_log",
        "forgejo_get_action_run_logs",
        "forgejo_list_action_run_artifacts",
        "forgejo_cancel_action_run",
        "forgejo_delete_action_run",
        "forgejo_dispatch_workflow",
        "forgejo_create_tag",
        "forgejo_create_release",
    ]
    assert get_tool("forgejo_get_current_user") is tools[0]
    assert tools[0].risk == "read"
    assert tools[0].input_schema["additionalProperties"] is False
    assert all(tool.output_schema["additionalProperties"] is False for tool in tools)
    assert get_tool("forgejo_update_repository").input_schema["minProperties"] == 3
    assert get_tool("forgejo_migrate_repository").risk == "write"
    assert get_tool("forgejo_sync_mirror").risk == "write"
    for tool in tools:
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        jsonschema.Draft202012Validator.check_schema(tool.output_schema)


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner": ".", "repo": "repo"},
        {"owner": "..", "repo": "repo"},
        {"owner": " .. ", "repo": "repo"},
        {"owner": "\u00a0..\u00a0", "repo": "repo"},
        {"owner": "\u3000.\u3000", "repo": "repo"},
        {"owner": "owner", "repo": "."},
        {"owner": "owner", "repo": ".."},
        {"owner": "owner", "repo": " . "},
        {"owner": "owner", "repo": "\u00a0..\u00a0"},
    ],
)
def test_repository_tool_schema_rejects_dot_segments(arguments: dict[str, str]) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_repository").input_schema)

    assert list(validator.iter_errors(arguments))


@pytest.mark.parametrize("sha", [".", "..", " . ", " .. ", "\u00a0..\u00a0", "\u3000.\u3000"])
def test_ref_tool_schema_rejects_dot_segments(sha: str) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_commit").input_schema)

    assert any(
        list(error.path) == ["sha"]
        for error in validator.iter_errors({"owner": "owner", "repo": "repo", "sha": sha})
    )


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "..",
        "./README.md",
        "src/./module.py",
        "src/../secret",
        "\u00a0..\u00a0",
        "\u00a0../README.md",
        "src/..\u3000",
        "\u3000/absolute",
    ],
)
def test_file_path_tool_schema_rejects_dot_segments(path: str) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_file_content").input_schema)

    assert any(
        list(error.path) == ["path"]
        for error in validator.iter_errors({"owner": "owner", "repo": "repo", "path": path})
    )


def test_repository_root_listing_accepts_an_omitted_or_empty_path() -> None:
    validator = jsonschema.Draft202012Validator(
        get_tool("forgejo_list_repository_contents").input_schema
    )

    assert not list(validator.iter_errors({"owner": "owner", "repo": "repo"}))
    assert not list(validator.iter_errors({"owner": "owner", "repo": "repo", "path": ""}))
    file_validator = jsonschema.Draft202012Validator(
        get_tool("forgejo_get_file_content").input_schema
    )
    assert list(file_validator.iter_errors({"owner": "owner", "repo": "repo", "path": ""}))


@pytest.mark.parametrize(
    ("failed_check", "reason"),
    [
        ("token_valid", "token_invalid"),
        ("user_enabled", "user_disabled"),
        ("global_tool_enabled", "tool_globally_disabled"),
        ("user_allowed_tool", "tool_not_allowed_for_user"),
        ("token_has_tool_grant", "tool_not_granted_to_token"),
        ("forgejo_credential_configured", "forgejo_credential_missing"),
    ],
)
def test_tool_authorization_defaults_to_deny(failed_check: str, reason: str) -> None:
    decision = authorize_tool(allowed_context(**{failed_check: False}))

    assert decision.allowed is False
    assert decision.reason == reason


def test_tool_authorization_allows_only_when_every_layer_passes() -> None:
    decision = authorize_tool(allowed_context())

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_batch_tool_authorization_loads_one_permission_snapshot() -> None:
    async def exercise() -> None:
        token_id = uuid.uuid4()
        user_id = uuid.uuid4()
        names = [tool.name for tool in list_tools()]
        globally_disabled = names[-1]
        settings = {
            name: SimpleNamespace(enabled=True) for name in names if name != globally_disabled
        }
        permissions = SimpleNamespace(
            settings=AsyncMock(return_value=settings),
            allowance_names=AsyncMock(return_value=set(names)),
            grant_names=AsyncMock(return_value=set(names)),
        )
        tokens = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=token_id,
                    user_id=user_id,
                    enabled=True,
                    revoked_at=None,
                    expires_at=None,
                    user=SimpleNamespace(
                        status=RecordStatus.ACTIVE,
                        forgejo_credentials=[SimpleNamespace(status=CredentialStatus.ACTIVE)],
                    ),
                )
            )
        )
        service = ToolPermissionService(MagicMock())
        service.permissions = permissions
        service.tokens = tokens

        decisions = await service.decisions(
            token_id=token_id,
            tool_names=(*names, "forgejo_unknown", names[0]),
        )

        assert decisions[names[0]].allowed is True
        assert decisions[globally_disabled].reason == "tool_globally_disabled"
        assert decisions["forgejo_unknown"].reason == "token_invalid"
        tokens.get.assert_awaited_once_with(token_id)
        permissions.settings.assert_awaited_once_with()
        permissions.allowance_names.assert_awaited_once_with(user_id)
        permissions.grant_names.assert_awaited_once_with(token_id)

    asyncio.run(exercise())


LIST_TOOLS_WITH_FIELDS = (
    "forgejo_list_repositories",
    "forgejo_list_issues",
    "forgejo_list_issue_comments",
    "forgejo_list_pull_requests",
)
_LIST_TOOL_BASE_ARGUMENTS: dict[str, dict[str, object]] = {
    "forgejo_list_repositories": {},
    "forgejo_list_issues": {"owner": "owner", "repo": "repo"},
    "forgejo_list_issue_comments": {"owner": "owner", "repo": "repo", "number": 1},
    "forgejo_list_pull_requests": {"owner": "owner", "repo": "repo"},
}


@pytest.mark.parametrize("tool_name", LIST_TOOLS_WITH_FIELDS)
def test_list_tool_fields_selector_is_a_closed_enum_defaulting_to_compact(tool_name: str) -> None:
    spec = get_tool(tool_name)
    fields = spec.input_schema["properties"]["fields"]
    validator = jsonschema.Draft202012Validator(spec.input_schema)
    base = _LIST_TOOL_BASE_ARGUMENTS[tool_name]

    assert fields == {"type": "string", "enum": ["compact", "full"], "default": "compact"}
    assert "fields" not in spec.input_schema["required"]
    assert not list(validator.iter_errors(base)), "fields must be optional"
    assert not list(validator.iter_errors({**base, "fields": "compact"}))
    assert not list(validator.iter_errors({**base, "fields": "full"}))
    assert any(
        list(error.path) == ["fields"]
        for error in validator.iter_errors({**base, "fields": "verbose"})
    )


@pytest.mark.parametrize("tool_name", LIST_TOOLS_WITH_FIELDS)
def test_list_tool_output_schema_requires_truncation_flag_and_relaxes_links(
    tool_name: str,
) -> None:
    item = get_tool(tool_name).output_schema["properties"]["items"]["items"]
    flag = "description_truncated" if tool_name == "forgejo_list_repositories" else "body_truncated"

    assert item["properties"][flag] == {"type": "boolean"}
    assert flag in item["required"]
    assert "html_url" in item["properties"]
    assert "html_url" not in item["required"]
    if "user" in item["properties"]:
        user = item["properties"]["user"]
        assert "avatar_url" in user["properties"]
        assert "avatar_url" not in user["required"]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"attempt": 2},
        {"max_bytes": 1, "from_end": False, "offset": 0},
        {"max_bytes": 1024 * 1024, "offset": 10 * 1024 * 1024, "grep": "g" * 256},
        {"grep": ""},
        {"filter": "none"},
        {"filter": "ci", "grep": "error", "max_bytes": 4096},
    ],
)
def test_action_job_log_schema_accepts_window_arguments(arguments: dict[str, object]) -> None:
    schema = get_tool("forgejo_get_action_job_log").input_schema

    jsonschema.validate(
        instance={"owner": "owner", "repo": "repo", "job_id": 51, **arguments}, schema=schema
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["max_bytes"]["default"] == 64 * 1024
    assert schema["properties"]["from_end"]["default"] is True
    assert schema["properties"]["offset"]["default"] == 0
    assert schema["properties"]["filter"] == {
        "type": "string",
        "enum": ["none", "ci"],
        "default": "none",
        "description": schema["properties"]["filter"]["description"],
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"max_bytes": 0},
        {"max_bytes": 1024 * 1024 + 1},
        {"max_bytes": "64"},
        {"from_end": "yes"},
        {"offset": -1},
        {"grep": "g" * 257},
        {"limit": 10},
        {"filter": "all"},
        {"filter": "CI"},
        {"filter": ""},
        {"filter": True},
        {"filter": None},
    ],
)
def test_action_job_log_schema_rejects_out_of_range_window_arguments(
    arguments: dict[str, object],
) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_action_job_log").input_schema)

    assert list(
        validator.iter_errors({"owner": "owner", "repo": "repo", "job_id": 51, **arguments})
    )


def test_action_log_output_schemas_describe_windows_and_index_entries() -> None:
    job_log = get_tool("forgejo_get_action_job_log").output_schema
    run_logs = get_tool("forgejo_get_action_run_logs").output_schema
    file_schema = run_logs["properties"]["files"]["items"]

    assert set(job_log["required"]) == {
        "job_id",
        "attempt",
        "size",
        "sha256",
        "content",
        "offset",
        "returned_bytes",
        "truncated",
    }
    assert set(file_schema["required"]) == {"name", "size", "sha256"}
    assert {"content", "offset", "returned_bytes", "truncated"} <= set(file_schema["properties"])
    assert file_schema["additionalProperties"] is False
    jsonschema.validate(
        instance={"name": "a.log", "size": 3, "sha256": "0" * 64}, schema=file_schema
    )
    assert "filter_stats" not in job_log["required"]
    assert "filter_stats" not in file_schema["required"]
    stats_schema = job_log["properties"]["filter_stats"]
    assert stats_schema == file_schema["properties"]["filter_stats"]
    assert set(stats_schema["required"]) == set(stats_schema["properties"]) == _FILTER_STATS_KEYS
    assert stats_schema["additionalProperties"] is False
    stats = dict.fromkeys(_FILTER_STATS_KEYS, 0)
    jsonschema.validate(
        instance={
            "job_id": 51,
            "attempt": None,
            "size": 3,
            "sha256": "0" * 64,
            "content": "",
            "offset": 0,
            "returned_bytes": 0,
            "truncated": False,
            "filter_stats": stats,
        },
        schema=job_log,
    )
    assert list(jsonschema.Draft202012Validator(stats_schema).iter_errors({**stats, "extra": 1}))
    assert list(
        jsonschema.Draft202012Validator(stats_schema).iter_errors({**stats, "removed_ansi": -1})
    )


_FILTER_STATS_KEYS = {
    "removed_ansi",
    "removed_carriage_returns",
    "removed_timestamps",
    "collapsed_lines",
    "removed_blank_lines",
    "original_lines",
    "filtered_lines",
}


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"include_content": True},
        {"include_content": True, "max_bytes_per_file": 1},
        {"include_content": False, "max_bytes_per_file": 1024 * 1024},
        {"include_content": True, "filter": "ci"},
        {"filter": "none"},
    ],
)
def test_action_run_logs_schema_accepts_index_arguments(arguments: dict[str, object]) -> None:
    schema = get_tool("forgejo_get_action_run_logs").input_schema

    jsonschema.validate(
        instance={"owner": "owner", "repo": "repo", "run_id": 42, **arguments}, schema=schema
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["include_content"]["default"] is False
    assert schema["properties"]["max_bytes_per_file"]["default"] == 64 * 1024
    assert schema["properties"]["filter"]["enum"] == ["none", "ci"]
    assert schema["properties"]["filter"]["default"] == "none"


@pytest.mark.parametrize(
    "arguments",
    [
        {"include_content": "true"},
        {"max_bytes_per_file": 0},
        {"max_bytes_per_file": 1024 * 1024 + 1},
        {"max_bytes": 10},
        {"filter": "raw"},
        {"filter": 1},
    ],
)
def test_action_run_logs_schema_rejects_invalid_arguments(arguments: dict[str, object]) -> None:
    validator = jsonschema.Draft202012Validator(
        get_tool("forgejo_get_action_run_logs").input_schema
    )

    assert list(
        validator.iter_errors({"owner": "owner", "repo": "repo", "run_id": 42, **arguments})
    )
