# Catalog comparison — Sqcows/forgejo-mcp (103 tools) vs this fork (50)

> Note Claude — comparison made on 2026-09-15 from the **README** of `github.com/Sqcows/forgejo-mcp` and from this repository's tool registry (instantiated, not eyeballed). **Their code was not audited**: their security claims (Zod validation, SSRF protection, rate limiting) are quoted from their README and were not verified. This document compares catalogs, not implementations.

## The announced count

The README announces "103 tools across 6 categories". The six tables total **102** entries (24+20+12+14+13+19). A one-unit gap, of no practical consequence, noted for accuracy.

Roughly **30 tools are common** to both catalogs (repository reads, issues, basic pull requests). They therefore have ~72 tools we lack; we have ~20 they lack.

## ⚠️ The two catalogs are not comparable as-is

| | Sqcows | This fork |
|---|---|---|
| Identity | **a single token** configured server-side | **per-user PAT**, verified, AES-256-GCM encrypted |
| Per-tool authorization | none | 6 fail-closed layers, re-evaluated on every call |
| Audit | none mentioned | receipt written before the call, redacted, read-only API |
| Transport | stdio, or HTTP with an **optional** Bearer | authenticated HTTP required, OAuth 2.1 or static Bearer |
| Admin tools | `admin_create_user`, `admin_delete_user`, `delete_repo`, `delete_org` | **excluded by doctrine** (`docs/known-limitations.md`) |

Their own README advises using a non-admin token when the admin tools are not needed: that is an admission that the only available granularity is the Forgejo token itself. Our catalog of 50 is a **governance decision**, not a capability ceiling. Part of their numerical lead is, on our side, a deliberate refusal.

## What they have that we do not — by real value

### 1. Blunt asymmetries in our catalog (worth closing, low cost)

We can write without being able to read:

| Missing tool | Why it hurts |
|---|---|
| `list_tags` | we have `forgejo_create_tag`, no way to list existing tags |
| `list_releases` | we have `forgejo_create_release`, no way to list releases |
| `get_branch` | we list branches, no single-item read |
| `get_label`, `get_milestone` | we list, without single-item reads |

An agent about to cut release `v1.3.0` cannot check that `v1.2.0` already exists. **This is the most embarrassing gap in the current catalog.**

### 2. Search — absent on our side

`search_repos`, `search_users`. An agent that does not already know the `owner/repo` pair is stuck: it can only list repositories visible to the PAT and filter client-side. On an instance with a few hundred repositories, that is token-expensive and brittle.

### 3. Issue triage lifecycle

`create_label`, `edit_label`, `delete_label`, `add_issue_labels`, `remove_issue_label`, `create_milestone`, `edit_milestone`, `delete_milestone`.

We can read labels and milestones, and set `label_ids` when creating an issue, but a triage agent can neither label an existing issue nor create the missing label. This is a very common agent workflow.

### 4. Comments — edit and delete

`edit_issue_comment`, `delete_issue_comment`. We can create a comment, never fix our own.

### 5. Contribution flow

`fork_repo`, `update_pr_branch` (merge or rebase the base into the pull request), `list_collaborators`, `add_collaborator`, `list_forks`.

`update_pr_branch` is the most useful of these: a pull request behind its base is a daily occurrence.

### 6. Agent comfort

`render_markdown` / `render_markup` (preview before publishing), `list_my_notifications` / `mark_notifications_read` (a reactive agent rather than a polling one), `list_gitignore_templates`, `list_license_templates` and their `get_*` counterparts (correct repository creation), `list_repo_topics` / `update_repo_topics`, `star_repo` / `unstar_repo`.

### 7. Organizations and users (27 tools)

Almost all of it is missing here: `list_orgs`, `get_org`, `list_org_repos`, `list_org_members`, `list_org_teams`, `get_user`, `list_user_repos`, `list_user_orgs`, `list_followers`. Useful read-side to situate a context, much less useful write-side for a development agent.

### 8. Outside our doctrine (~20 tools)

`admin_list_users`, `admin_create_user`, `admin_edit_user`, `admin_delete_user`, `admin_list_cron_jobs`, `admin_run_cron_job`, `admin_list_hooks`, `list_org_hooks`, `get_runner_registration_token`, `delete_repo`, `delete_org`, `transfer_repo`, `create_team`, `add_team_member`, `remove_team_member`, `delete_branch`, `delete_file`.

`docs/known-limitations.md` excludes these explicitly. `get_runner_registration_token` deserves its own mention: that token registers a runner, therefore it allows code execution on the CI infrastructure. Exposing it to an agent is a heavy decision.

## What we have and they do not

| Area | Our tools | On their side |
|---|---|---|
| **Forgejo Actions** | `list_action_runs`, `get_action_run`, `list_action_run_jobs`, `get_action_job_log`, `get_action_run_logs`, `list_action_run_artifacts`, `cancel_action_run`, `delete_action_run`, `dispatch_workflow` | `list_action_runners_jobs` and `get_runner_registration_token` only — runner side, not CI side |
| **Mirrors / migration** | `migrate_repository`, `sync_mirror`, `update_repository` (mirror interval, prune) | absent |
| **Atomic multi-file commit** | `commit_changes`: up to 100 files, create/update/delete/move in **one** commit | `create_file` / `update_file` / `delete_file`, one commit per file |
| **Git inspection** | `compare_refs`, `get_git_tree`, `get_commit_status` | absent |
| **Fine-grained PR** | `get_pull_request_merge_status`, `get_pull_request_review` (single), `remove_pull_request_reviewers` | absent |

CI diagnosis is our clearest advantage: reading the logs of a failing job is impossible on their side. `commit_changes` is also qualitatively better than three per-file tools — an agent editing five files produces one commit here, five there.

## Recommendations

**Worth adding first** (decreasing value, all read-only or bounded writes, compatible with our authorization model):

1. `list_tags`, `list_releases` — close a blunt asymmetry, minimal effort
2. `search_repositories` — unblocks the agent that does not know the repository
3. `add_issue_labels`, `remove_issue_label`, `create_label`, `update_label` — issue triage
4. `create_milestone`, `update_milestone` — milestone tracking
5. `update_issue_comment`, `delete_issue_comment` — fix our own comment
6. `update_pull_request_branch` — pull request behind its base
7. `get_branch`, `get_label`, `get_milestone` — completeness at no cost
8. `fork_repository` — contribution flow
9. `render_markdown` — preview

That is **~15 tools**, taking the catalog to ~65 without touching the governance doctrine. Each one must ship with its permission entry, bounded schema, audit target and tests — the real per-tool cost is not the HTTP wrapper.

**Not worth taking**: user administration, repository and organization deletion, team management, system webhooks, cron jobs and the runner registration token. These are precisely the capabilities a governance layer exists in order not to delegate to an agent.

**To check before reusing any code**: their implementation was not audited. Their size bounds on file contents are undocumented, their HTTP endpoint is authenticated optionally, and no audit trail is mentioned. Take catalog ideas, not lines of code.
