from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    field_validator,
    model_serializer,
)

from forgejo_mcp.application.errors import ExternalServiceUnavailable
from forgejo_mcp.forgejo.excerpt import excerpt

ListFields = Literal["compact", "full"]
LIST_FIELDS: frozenset[str] = frozenset({"compact", "full"})


class RepositorySummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    owner: str
    name: str
    full_name: str
    description: str
    private: bool
    fork: bool
    default_branch: str
    archived: bool
    html_url: str
    updated_at: datetime | None
    stars_count: int | None = None
    forks_count: int | None = None
    open_issues_count: int | None = None
    permissions: dict[str, bool] | None = None


class BranchSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    commit_sha: str
    protected: bool


class CommitStats(BaseModel):
    model_config = ConfigDict(strict=True)

    additions: int
    deletions: int
    total: int


class CommitFileSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    path: str
    status: str
    additions: int | None = None
    deletions: int | None = None
    changes: int | None = None


class CommitSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    sha: str
    message: str
    html_url: str | None
    author_name: str | None
    author_email: str | None
    authored_at: datetime | None
    committer_name: str | None
    committed_at: datetime | None
    parent_shas: list[str]
    stats: CommitStats | None


class CommitDetail(CommitSummary):
    files: list[CommitFileSummary]
    files_truncated: bool


class CompareSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    base: str
    head: str
    total_commits: int
    commits: list[CommitSummary]
    files: list[CommitFileSummary]
    commits_truncated: bool
    files_truncated: bool


class GitTreeEntry(BaseModel):
    model_config = ConfigDict(strict=True)

    path: str
    mode: str
    type: str
    size: int
    sha: str


class GitTreeSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    sha: str
    entries: list[GitTreeEntry]
    page: int
    limit: int
    total_count: int
    truncated: bool


class UserSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    username: str
    display_name: str | None
    avatar_url: str | None


class LabelSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    name: str
    color: str


class MilestoneSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    title: str


class RepositoryLabelSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    name: str
    color: str
    description: str
    exclusive: bool
    archived: bool


class RepositoryMilestoneSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    title: str
    description: str
    state: str
    open_issues: int
    closed_issues: int
    created_at: datetime
    updated_at: datetime
    due_on: datetime | None
    closed_at: datetime | None


class IssueSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    number: int
    title: str
    body: str | None
    state: str
    html_url: str
    user: UserSummary
    assignees: list[UserSummary]
    labels: list[LabelSummary]
    milestone: MilestoneSummary | None
    comments_count: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class CommentSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    body: str
    html_url: str | None
    user: UserSummary
    created_at: datetime
    updated_at: datetime


class PullRefSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    ref: str
    sha: str
    repository: str


class PullRequestSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    number: int
    title: str
    body: str | None
    state: str
    draft: bool
    mergeable: bool | None
    merged: bool
    html_url: str
    user: UserSummary
    base: PullRefSummary
    head: PullRefSummary
    labels: list[LabelSummary]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    merged_at: datetime | None
    commits_count: int | None = None
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None


class FileContent(BaseModel):
    model_config = ConfigDict(strict=True)

    path: str
    name: str
    sha: str
    ref: str | None
    size: int
    encoding: str
    content: str
    html_url: str | None


class _ListItem(BaseModel):
    """Base for list tool items: link fields left unset (compact form) are omitted."""

    model_config = ConfigDict(strict=True)
    _compact_omits: ClassVar[frozenset[str]] = frozenset()

    @model_serializer(mode="wrap")
    def _omit_unset_link_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for name in self._compact_omits - self.model_fields_set:
            data.pop(name, None)
        return data


class UserListItem(_ListItem):
    _compact_omits: ClassVar[frozenset[str]] = frozenset({"avatar_url"})

    id: int
    username: str
    display_name: str | None
    avatar_url: str | None = None


class RepositoryListItem(_ListItem):
    _compact_omits: ClassVar[frozenset[str]] = frozenset({"html_url"})

    id: int
    owner: str
    name: str
    full_name: str
    description: str
    description_truncated: bool
    private: bool
    fork: bool
    default_branch: str
    archived: bool
    html_url: str | None = None
    updated_at: datetime | None
    stars_count: int | None = None
    forks_count: int | None = None
    open_issues_count: int | None = None
    permissions: dict[str, bool] | None = None


class IssueListItem(_ListItem):
    _compact_omits: ClassVar[frozenset[str]] = frozenset({"html_url"})

    number: int
    title: str
    body: str | None
    body_truncated: bool
    state: str
    html_url: str | None = None
    user: UserListItem
    assignees: list[UserListItem]
    labels: list[LabelSummary]
    milestone: MilestoneSummary | None
    comments_count: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class CommentListItem(_ListItem):
    _compact_omits: ClassVar[frozenset[str]] = frozenset({"html_url"})

    id: int
    body: str
    body_truncated: bool
    html_url: str | None = None
    user: UserListItem
    created_at: datetime
    updated_at: datetime


class PullRequestListItem(_ListItem):
    _compact_omits: ClassVar[frozenset[str]] = frozenset({"html_url"})

    number: int
    title: str
    body: str | None
    body_truncated: bool
    state: str
    draft: bool
    mergeable: bool | None
    merged: bool
    html_url: str | None = None
    user: UserListItem
    base: PullRefSummary
    head: PullRefSummary
    labels: list[LabelSummary]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    merged_at: datetime | None
    commits_count: int | None = None
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None


class _UserPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(default=0, ge=0)
    login: str = Field(min_length=1, max_length=255)
    full_name: str | None = None
    avatar_url: str | None = None


class _PermissionPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    admin: bool = False
    pull: bool = False
    push: bool = False


class _RepositoryPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)
    owner: _UserPayload
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=511)
    description: str = ""
    private: bool = False
    fork: bool = False
    default_branch: str = ""
    archived: bool = False
    html_url: str = ""
    updated_at: datetime | None = None
    stars_count: int | None = Field(default=None, ge=0)
    forks_count: int | None = Field(default=None, ge=0)
    open_issues_count: int | None = Field(default=None, ge=0)
    permissions: _PermissionPayload | None = None

    @field_validator("updated_at", mode="before")
    @classmethod
    def parse_updated_at(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class _CommitPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str = Field(min_length=1, max_length=64)


class _BranchPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=255)
    commit: _CommitPayload
    protected: bool = False


class _CommitUserPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str | None = None
    email: str | None = None
    date: datetime | None = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class _CommitMetaPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    sha: str = Field(min_length=1, max_length=64)


class _CommitStatsPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class _CommitFilePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    filename: str = Field(min_length=1, max_length=1024)
    status: str = Field(default="modified", max_length=40)
    additions: int | None = Field(default=None, ge=0)
    deletions: int | None = Field(default=None, ge=0)
    changes: int | None = Field(default=None, ge=0)


class _RepoCommitPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    message: str = ""
    author: _CommitUserPayload | None = None
    committer: _CommitUserPayload | None = None


class _FullCommitPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    sha: str = Field(min_length=1, max_length=64)
    commit: _RepoCommitPayload
    html_url: str | None = None
    parents: list[_CommitMetaPayload] = Field(default_factory=list)
    stats: _CommitStatsPayload | None = None
    files: list[_CommitFilePayload] | None = Field(default_factory=list)


class _ComparePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    total_commits: int = Field(default=0, ge=0)
    commits: list[_FullCommitPayload] = Field(default_factory=list)
    files: list[_CommitFilePayload] | None = Field(default_factory=list)


class _GitTreeEntryPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    path: str = Field(min_length=1, max_length=1024)
    mode: str = ""
    type: str = Field(min_length=1, max_length=40)
    size: int = Field(default=0, ge=0)
    sha: str = Field(min_length=1, max_length=64)


class _GitTreePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    sha: str = Field(min_length=1, max_length=64)
    page: int = Field(default=1, ge=1)
    total_count: int = Field(default=0, ge=0)
    tree: list[_GitTreeEntryPayload] = Field(default_factory=list)
    truncated: bool = False


class _LabelPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)
    name: str
    color: str = ""


class _MilestonePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)
    title: str


class _RepositoryLabelPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)
    name: str
    color: str = ""
    description: str = ""
    exclusive: bool = False
    is_archived: bool = False


class _RepositoryMilestonePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)
    title: str
    description: str = ""
    state: str
    open_issues: int = Field(default=0, ge=0)
    closed_issues: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    due_on: datetime | None = None
    closed_at: datetime | None = None

    @field_validator("created_at", "updated_at", "due_on", "closed_at", mode="before")
    @classmethod
    def parse_dates(cls, value: object) -> object:
        return _parse_datetime(value)


class _IssuePayload(BaseModel):
    model_config = ConfigDict(strict=True)

    number: int = Field(gt=0)
    title: str
    body: str | None = None
    state: str
    html_url: str
    user: _UserPayload
    assignees: list[_UserPayload] | None = Field(default_factory=list)
    labels: list[_LabelPayload] = Field(default_factory=list)
    milestone: _MilestonePayload | None = None
    comments: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None

    @field_validator("created_at", "updated_at", "closed_at", mode="before")
    @classmethod
    def parse_dates(cls, value: object) -> object:
        return _parse_datetime(value)


class _CommentPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)
    body: str
    html_url: str | None = None
    user: _UserPayload
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def parse_dates(cls, value: object) -> object:
        return _parse_datetime(value)


class _PullRepositoryPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    full_name: str


class _PullRefPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    ref: str
    sha: str
    repo: _PullRepositoryPayload


class _PullRequestPayload(BaseModel):
    model_config = ConfigDict(strict=True)

    number: int = Field(gt=0)
    title: str
    body: str | None = None
    state: str
    draft: bool = False
    mergeable: bool | None = None
    merged: bool = False
    html_url: str
    user: _UserPayload
    base: _PullRefPayload
    head: _PullRefPayload
    labels: list[_LabelPayload] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    commits: int | None = Field(default=None, ge=0)
    additions: int | None = Field(default=None, ge=0)
    deletions: int | None = Field(default=None, ge=0)
    changed_files: int | None = Field(default=None, ge=0)

    @field_validator("created_at", "updated_at", "closed_at", "merged_at", mode="before")
    @classmethod
    def parse_dates(cls, value: object) -> object:
        return _parse_datetime(value)


def _parse_datetime(value: object) -> object:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if isinstance(parsed, datetime) and parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def parse_repository(payload: Any) -> RepositorySummary:
    try:
        record = _RepositoryPayload.model_validate(payload)
    except ValidationError as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid repository response"
        ) from error
    return RepositorySummary(
        id=record.id,
        owner=record.owner.login,
        name=record.name,
        full_name=record.full_name,
        description=record.description,
        private=record.private,
        fork=record.fork,
        default_branch=record.default_branch,
        archived=record.archived,
        html_url=record.html_url,
        updated_at=record.updated_at,
        stars_count=record.stars_count,
        forks_count=record.forks_count,
        open_issues_count=record.open_issues_count,
        permissions=(record.permissions.model_dump() if record.permissions is not None else None),
    )


def parse_repositories(payload: Any) -> list[RepositorySummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid repository list response")
    return [parse_repository(item) for item in payload]


def _commit_summary(record: _FullCommitPayload) -> CommitSummary:
    author = record.commit.author
    committer = record.commit.committer
    return CommitSummary(
        sha=record.sha,
        message=record.commit.message,
        html_url=record.html_url,
        author_name=author.name if author is not None else None,
        author_email=author.email if author is not None else None,
        authored_at=author.date if author is not None else None,
        committer_name=committer.name if committer is not None else None,
        committed_at=committer.date if committer is not None else None,
        parent_shas=[parent.sha for parent in record.parents],
        stats=(
            CommitStats(
                additions=record.stats.additions,
                deletions=record.stats.deletions,
                total=record.stats.total,
            )
            if record.stats is not None
            else None
        ),
    )


def _file_summary(record: _CommitFilePayload) -> CommitFileSummary:
    return CommitFileSummary(
        path=record.filename,
        status=record.status,
        additions=record.additions,
        deletions=record.deletions,
        changes=record.changes,
    )


def parse_commits(payload: Any) -> list[CommitSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid commit list response")
    try:
        return [_commit_summary(_FullCommitPayload.model_validate(item)) for item in payload]
    except ValidationError as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid commit list response"
        ) from error


def parse_commit(payload: Any) -> CommitDetail:
    try:
        record = _FullCommitPayload.model_validate(payload)
    except ValidationError as error:
        raise ExternalServiceUnavailable("Forgejo returned an invalid commit response") from error
    summary = _commit_summary(record)
    record_files = record.files or []
    files = [_file_summary(item) for item in record_files[:100]]
    return CommitDetail(
        **summary.model_dump(),
        files=files,
        files_truncated=len(record_files) > 100,
    )


def parse_compare(payload: Any, *, base: str, head: str) -> CompareSummary:
    try:
        record = _ComparePayload.model_validate(payload)
    except ValidationError as error:
        raise ExternalServiceUnavailable("Forgejo returned an invalid compare response") from error
    record_files = record.files or []
    return CompareSummary(
        base=base,
        head=head,
        total_commits=record.total_commits,
        commits=[_commit_summary(item) for item in record.commits[:100]],
        files=[_file_summary(item) for item in record_files[:100]],
        commits_truncated=len(record.commits) > 100,
        files_truncated=len(record_files) > 100,
    )


def parse_git_tree(payload: Any, *, page: int, limit: int) -> GitTreeSummary:
    try:
        record = _GitTreePayload.model_validate(payload)
    except ValidationError as error:
        raise ExternalServiceUnavailable("Forgejo returned an invalid git tree response") from error
    return GitTreeSummary(
        sha=record.sha,
        entries=[
            GitTreeEntry(
                path=item.path,
                mode=item.mode,
                type=item.type,
                size=item.size,
                sha=item.sha,
            )
            for item in record.tree
        ],
        page=page,
        limit=limit,
        total_count=record.total_count,
        truncated=record.truncated,
    )


def parse_repository_labels(payload: Any) -> list[RepositoryLabelSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid label list response")
    try:
        records = [_RepositoryLabelPayload.model_validate(item) for item in payload]
    except ValidationError as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid label list response"
        ) from error
    return [
        RepositoryLabelSummary(
            id=item.id,
            name=item.name,
            color=item.color,
            description=item.description,
            exclusive=item.exclusive,
            archived=item.is_archived,
        )
        for item in records
    ]


def parse_repository_milestones(payload: Any) -> list[RepositoryMilestoneSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid milestone list response")
    try:
        records = [_RepositoryMilestonePayload.model_validate(item) for item in payload]
    except ValidationError as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid milestone list response"
        ) from error
    if any(item.state not in {"open", "closed"} for item in records):
        raise ExternalServiceUnavailable("Forgejo returned an invalid milestone list response")
    return [
        RepositoryMilestoneSummary(
            id=item.id,
            title=item.title,
            description=item.description,
            state=item.state,
            open_issues=item.open_issues,
            closed_issues=item.closed_issues,
            created_at=item.created_at,
            updated_at=item.updated_at,
            due_on=item.due_on,
            closed_at=item.closed_at,
        )
        for item in records
    ]


def parse_branches(payload: Any) -> list[BranchSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid branch list response")
    branches: list[BranchSummary] = []
    try:
        for item in payload:
            record = _BranchPayload.model_validate(item)
            branches.append(
                BranchSummary(
                    name=record.name,
                    commit_sha=record.commit.id,
                    protected=record.protected,
                )
            )
    except ValidationError as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid branch list response"
        ) from error
    return branches


def _user_summary(record: _UserPayload) -> UserSummary:
    return UserSummary(
        id=record.id,
        username=record.login,
        display_name=record.full_name or None,
        avatar_url=record.avatar_url,
    )


def _labels(records: list[_LabelPayload]) -> list[LabelSummary]:
    return [LabelSummary(id=item.id, name=item.name, color=item.color) for item in records]


def _issue_summary(record: _IssuePayload) -> IssueSummary:
    if record.state not in {"open", "closed"}:
        raise ValueError("invalid issue state")
    return IssueSummary(
        number=record.number,
        title=record.title,
        body=record.body,
        state=record.state,
        html_url=record.html_url,
        user=_user_summary(record.user),
        assignees=[_user_summary(item) for item in record.assignees or []],
        labels=_labels(record.labels),
        milestone=(
            MilestoneSummary(id=record.milestone.id, title=record.milestone.title)
            if record.milestone is not None
            else None
        ),
        comments_count=record.comments,
        created_at=record.created_at,
        updated_at=record.updated_at,
        closed_at=record.closed_at,
    )


def parse_issue(payload: Any) -> IssueSummary:
    try:
        return _issue_summary(_IssuePayload.model_validate(payload))
    except (ValidationError, ValueError) as error:
        raise ExternalServiceUnavailable("Forgejo returned an invalid issue response") from error


def parse_issues(payload: Any) -> list[IssueSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid issue list response")
    try:
        return [_issue_summary(_IssuePayload.model_validate(item)) for item in payload]
    except (ValidationError, ValueError) as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid issue list response"
        ) from error


def _comment_summary(record: _CommentPayload) -> CommentSummary:
    return CommentSummary(
        id=record.id,
        body=record.body,
        html_url=record.html_url,
        user=_user_summary(record.user),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def parse_comment(payload: Any) -> CommentSummary:
    try:
        return _comment_summary(_CommentPayload.model_validate(payload))
    except ValidationError as error:
        raise ExternalServiceUnavailable("Forgejo returned an invalid comment response") from error


def parse_comments(payload: Any) -> list[CommentSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid comment list response")
    try:
        return [_comment_summary(_CommentPayload.model_validate(item)) for item in payload]
    except ValidationError as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid comment list response"
        ) from error


def _pull_request_summary(record: _PullRequestPayload) -> PullRequestSummary:
    if record.state not in {"open", "closed"}:
        raise ValueError("invalid pull request state")
    return PullRequestSummary(
        number=record.number,
        title=record.title,
        body=record.body,
        state=record.state,
        draft=record.draft,
        mergeable=record.mergeable,
        merged=record.merged,
        html_url=record.html_url,
        user=_user_summary(record.user),
        base=PullRefSummary(
            ref=record.base.ref, sha=record.base.sha, repository=record.base.repo.full_name
        ),
        head=PullRefSummary(
            ref=record.head.ref, sha=record.head.sha, repository=record.head.repo.full_name
        ),
        labels=_labels(record.labels),
        created_at=record.created_at,
        updated_at=record.updated_at,
        closed_at=record.closed_at,
        merged_at=record.merged_at,
        commits_count=record.commits,
        additions=record.additions,
        deletions=record.deletions,
        changed_files=record.changed_files,
    )


def parse_pull_request(payload: Any) -> PullRequestSummary:
    try:
        return _pull_request_summary(_PullRequestPayload.model_validate(payload))
    except (ValidationError, ValueError) as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid pull request response"
        ) from error


def parse_pull_requests(payload: Any) -> list[PullRequestSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceUnavailable("Forgejo returned an invalid pull request list response")
    try:
        return [_pull_request_summary(_PullRequestPayload.model_validate(item)) for item in payload]
    except (ValidationError, ValueError) as error:
        raise ExternalServiceUnavailable(
            "Forgejo returned an invalid pull request list response"
        ) from error


def _user_list_item(user: UserSummary, fields: str) -> UserListItem:
    links = {"avatar_url": user.avatar_url} if fields == "full" else {}
    return UserListItem(id=user.id, username=user.username, display_name=user.display_name, **links)


def _bounded_text(text: str | None, fields: str) -> tuple[str | None, bool]:
    if fields == "full":
        return text, False
    return excerpt(text)


def repository_list_item(repository: RepositorySummary, *, fields: str) -> RepositoryListItem:
    description, truncated = _bounded_text(repository.description, fields)
    links = {"html_url": repository.html_url} if fields == "full" else {}
    return RepositoryListItem(
        id=repository.id,
        owner=repository.owner,
        name=repository.name,
        full_name=repository.full_name,
        description=description or "",
        description_truncated=truncated,
        private=repository.private,
        fork=repository.fork,
        default_branch=repository.default_branch,
        archived=repository.archived,
        updated_at=repository.updated_at,
        stars_count=repository.stars_count,
        forks_count=repository.forks_count,
        open_issues_count=repository.open_issues_count,
        permissions=repository.permissions,
        **links,
    )


def issue_list_item(issue: IssueSummary, *, fields: str) -> IssueListItem:
    body, truncated = _bounded_text(issue.body, fields)
    links = {"html_url": issue.html_url} if fields == "full" else {}
    return IssueListItem(
        number=issue.number,
        title=issue.title,
        body=body,
        body_truncated=truncated,
        state=issue.state,
        user=_user_list_item(issue.user, fields),
        assignees=[_user_list_item(item, fields) for item in issue.assignees],
        labels=issue.labels,
        milestone=issue.milestone,
        comments_count=issue.comments_count,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        closed_at=issue.closed_at,
        **links,
    )


def comment_list_item(comment: CommentSummary, *, fields: str) -> CommentListItem:
    body, truncated = _bounded_text(comment.body, fields)
    links = {"html_url": comment.html_url} if fields == "full" else {}
    return CommentListItem(
        id=comment.id,
        body=body or "",
        body_truncated=truncated,
        user=_user_list_item(comment.user, fields),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        **links,
    )


def pull_request_list_item(pull: PullRequestSummary, *, fields: str) -> PullRequestListItem:
    body, truncated = _bounded_text(pull.body, fields)
    links = {"html_url": pull.html_url} if fields == "full" else {}
    return PullRequestListItem(
        number=pull.number,
        title=pull.title,
        body=body,
        body_truncated=truncated,
        state=pull.state,
        draft=pull.draft,
        mergeable=pull.mergeable,
        merged=pull.merged,
        user=_user_list_item(pull.user, fields),
        base=pull.base,
        head=pull.head,
        labels=pull.labels,
        created_at=pull.created_at,
        updated_at=pull.updated_at,
        closed_at=pull.closed_at,
        merged_at=pull.merged_at,
        commits_count=pull.commits_count,
        additions=pull.additions,
        deletions=pull.deletions,
        changed_files=pull.changed_files,
        **links,
    )
