# External security audit — forgejo-mcp (fork)

> Note Claude — read-only audit performed on 2026-09-02 against a local checkout of the fork, in 4 parallel passes (malware/supply-chain, auth/OAuth 2.1, crypto/credentials, tool layer/Forgejo client), cross-checked against the repository self-audit (`docs/security/security-audit-2026-08-31.md`). No source file was modified.

---

## Initial disposition of commit `38bde2d` (before counter-audit)

> This historical section describes the first remediation as it was declared at commit `38bde2d`. The adverse counter-audit that follows then demonstrated two incomplete medium fixes and several low-severity reservations. The original Claude report and its counter-audit are preserved in full; the final disposition of the follow-up fix is appended after the counter-audit.

| # | Disposition | Fix / residual risk |
|---|---|---|
| 1 — High, dot segments | **Fixed** | `.` and `..` are rejected for owner, organization, repository and refs both by the MCP schemas and by Forgejo client validation, before any URL construction (`forgejo/client.py:2232-2267`, `tools/registry.py:90-158`). Witness tests cover the client and the schemas. |
| 2 — High, empty allowlist | **Fixed** | An empty Forgejo allowlist now rejects every connection in all environments (`config.py:139-148`). Production additionally continues to refuse to start without an allowlist. |
| 3 — Medium, IP/proxy/rate limit | **Fixed, with a documented limit** | `X-Forwarded-For` is accepted only from `FMCP_TRUSTED_PROXY_CIDRS`, then walked right to left (`auth/client_ip.py:10-49`). The in-memory tables are bounded, locked and purged (`auth/rate_limit.py:9-131`). They remain single-process and are reset on restart. |
| 4 — Medium, credentials in `clone_addr` | **Fixed** | The user-info of any URL is neutralized recursively before the audit receipt is written, including when tool validation subsequently fails (`audit/redaction.py:18-76`). |
| 5 — Medium, commit content | **Fixed** | Every `changes[].content` is replaced before persistence by a redaction marker, its UTF-8 size and its SHA-256 (`audit/redaction.py:44-70`). |
| 6 — Medium, `verify_tls=false` | **Fixed** | The Dashboard choice is no longer sufficient: it requires the separate deployment opt-in `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=true` (`config.py:33`, `application/forgejo_instance_service.py:35-45`). The default value remains `false`. |
| 7 — Composite medium, migration/supply-chain/exposure | **Partially fixed, residual documented** | Compose publishes the App and the test Forgejo on loopback by default and disables Uvicorn's implicit trust in proxy headers (`deploy/compose.yaml:52-54,102-105`). Final DNS resolution for migrations is still performed by Forgejo: its migration policy and egress controls remain mandatory. Images and Actions remain versioned by tags, not by immutable digests/SHAs. |
| 8–17 — Low | **Reduced or documented** | The `api_key`, `private_key` and `passwd` keys are now treated as sensitive without using the dangerous `pat` fragment; the limiters are bounded. TTL/replay/session/rotation and other low-severity limits remain in the known limitations where they do not warrant a compatibility-breaking change. |

### Verdict declared for `38bde2d` before counter-audit

- **Critical: 0** known finding.
- **High: 0** uncorrected among the two external findings.
- **Medium:** no confirmed application defect left untreated; what remains are the explicitly documented operational risks (Forgejo DNS resolution, immutable pinning, single-replica in-memory state, and operator TLS termination).
- **Permissions:** no additional Forgejo PAT scope, MCP tool, MCP grant or GitHub permission is added by these fixes.

### Historical branch validation at commit `e53b3fa`

- Python: **135 tests collected, 134 passed and 1 E2E requiring external credentials skipped**; PostgreSQL migrations applied on a throwaway database.
- Quality: Ruff check/format and MyPy strict pass; ESLint, TypeScript and the Vite build pass.
- Dependencies: `pip-audit` and `npm audit` report **0 known vulnerability**.
- Static analysis: Bandit reports **0 medium / 0 high**; its 24 low alerts are narrowing asserts or reviewed protocol literals.
- Secrets: Gitleaks reports **0 leak** in the worktree and in the published history; the detect-secrets candidates were classified as placeholders, synthetic E2E credentials, redaction examples or checksums.
- E2E: all **50 tools** pass against Forgejo 16.0.2 and 16.0.3, covering login, repositories, branches, commits, pull requests, issues, releases, files, search, webhooks, Actions, OAuth and MCP `2025-06-18`.
- Swagger: only 2 structural differences — version and required fields of `IssueMeta` — with **0 endpoint difference**.

---

## 🔁 Counter-audit of the remediation patch (2026-09-02, evening)

> Note Claude — **adverse** counter-verification of remediation commit `38bde2d`, independent of the "Disposition after remediation" section above (written by the patch author). Every fix was attacked with witnesses executed through the project venv; the full patch diff was re-read; the tests, Ruff and MyPy were re-run by the auditor (not merely taken on trust).

### Patch integrity: ✅ confirmed

- A single remediation commit (`38bde2d`, 44 files, +960/−132), pushed to `origin/compat/forgejo-16.0.3` (clean working tree, matching `ls-remote`, 14 published commits confirmed).
- No suspicious code in the diff (no eval/subprocess/new network domain), no runtime dependency changed (dev-only pytest/pytest-asyncio bumps), no test doctored to pass, no secret in the diff.
- Re-run by the auditor: `pytest tests/unit` → **112 passed**; 120 tests collected with integration (consistent with the announcement); `ruff check` and `mypy src` → 0 error. Not re-verified locally: Bandit, Gitleaks, pip-audit/npm audit, the 50-tool E2E.

### Verdict per claimed fix

| Original finding | Claim | Adverse verdict |
|---|---|---|
| 1 — HIGH dot segments | Fixed | ✅ **CONFIRMED** — `..`/`.`/`%2e%2e`/Unicode witnesses executed (0 request emitted on `owner=".."`), exhaustive inventory of the parameters interpolated into paths: none missed. 2 non-exploitable residuals: the schema pattern alone lets `" .. "` through (stopped by the client after `strip()` — the "equivalent after strip" class only holds on one layer); `_file_path` accepts `.` segments (cosmetic, intra-repo). |
| 2 — HIGH empty allowlist | Fixed | ✅ **CONFIRMED** — executed: dev without an allowlist → refusal; the 3 guard points (connection test, PAT verify, every tool call) verified; no URL-comparison variant gets through (trailing slash/case normalized, `:443`/userinfo/IDN → closed refusal); non-conforming base_url in DB → fail-closed. |
| 3 — MED. IP/proxy/rate limit | Fixed | ✅ **CONFIRMED with 2 reservations** — right-to-left algorithm correct (15/15 witnesses, simple spoof impossible, IPv4-mapped unwrapped, fail-safe on malformed input); limiters bounded fail-closed, eviction not bypassable by spray. Reservations: **duplicated `X-Forwarded-For` headers** — starlette's `headers.get()` reads only the first, so a proxy that adds a 2nd line instead of appending lets the attacker's header win (proven; fix: `getlist` + join); a burst of concurrent logins exceeds the cap of 5 (`check()`/`failure()` are not atomic with respect to each other). |
| 4 — MED. credentials in URL | Fixed | ⚠️ **PARTIAL — residual leak proven**: the `redacted_arguments` channel is indeed fixed (userinfo neutralized recursively, receipt→validation ordering preserved, test with credentials added), **but the same receipt persists `target=extract_target(arguments)` over the RAW arguments** (`tool_invocation_service.py:122`, `redaction.py:83-89`): witness executed — `{"repo": "https://bot:ghp_secret@github.com/o/r.git"}` → `ghp_secret` **in cleartext** in the audit's `target` field, before validation. The original flaw, moved into the neighboring field. Secondary limits: schemeless URLs (`u:p@host/…`, scp-like) are not covered by the pattern. |
| 5 — MED. commit contents | Fixed | ✅ **CONFIRMED** — `{redacted, bytes, sha256}` replacement executed on a realistic payload, SHA-256 and UTF-8 size correct. Narrow scope assumed: the exact `changes[].content` path only; bodies/comments are still archived in cleartext ≤ 4 KB (documented limitation, not a new hole). |
| 6 — MED. verify_tls opt-in | Fixed | ⚠️ **PARTIAL — guard at registration only**: `allow_unverified_forgejo_tls` is consulted only in `check()` (`forgejo_instance_service.py:39-42`). At **use time**, `forgejo_credential_service.py:92-97` and `forgejo_tool_service.py:377-396` honor `instance.verify_tls` as-is, without the flag, and **no migration purges an inherited `verify_tls=false`**: an instance registered before the patch stays unverified on every PAT-bearing call. Asymmetry with the allowlist (which is revalidated at all 3 points). Fix: repeat the guard in `_connection` and `verify`, or force `verify_tls=True` without the flag. |
| 8-17 — sensitive fragments | Reduced | ✅ **CONFIRMED with a hole** — `api_key`/`passwd`/`private_key` redacted, `path` not falsely redacted, `pat` avoided as intended; **but `apiKey`/`privateKey` in camelCase pass through in cleartext** (normalization does not break camelCase, and the audit record precedes key validation). |

### Out-of-scope items noted in the diff

- **OAuth `resource` relaxation (RFC 8707)**: mandatory → optional at `/token` and at authorization, with removal of the `missing_resource` assertion. Documented (CHANGELOG + `docs/security/oauth-2.1.md`), defensible in a single-resource setup, rejection of an incorrect `resource` still tested — but it is the patch's only **step backward**, slipped into a "harden" commit. To be ratified as a product decision.
- `deploy/Dockerfile:31`: the `CMD` keeps `--host 0.0.0.0` **without** `--no-proxy-headers` — the proxy hardening lives only in the compose override; an image launched directly falls back to the Uvicorn default.

### Findings remaining after the patch (prioritized)

1. 🟠 **MEDIUM** — `extract_target` persists raw, unredacted fields in the audit receipt (same class as original finding #4). Fix: apply URL redaction + bounding to the extracted values.
2. 🟠 **MEDIUM** — inherited `verify_tls=false` in the DB is honored at use time without the deployment flag; add the guard at the use points or migrate the state.
3. 🟡 LOW — merge duplicated `X-Forwarded-For` headers (`getlist` + join) in `auth/client_ip.py`.
4. 🟡 LOW — normalize camelCase in `_sensitive_key` (or add `apikey`/`privatekey` to the fragments).
5. 🟡 LOW — `--no-proxy-headers` in the Dockerfile `CMD`; strip on the schema side (align the two dot-segment layers); burst of concurrent logins; schemeless URLs in the redaction pattern.

### Verdict after counter-audit

The **2 HIGH flaws are genuinely fixed** (confirmed by attack, not by reading the author's tests). The patch has integrity — no malicious code, no hidden regression apart from the documented OAuth relaxation. But the "Disposition after remediation" section above **overstates two fixes**: findings 4 and 6 are partial (`extract_target` leak proven by execution; TLS guard absent from the use points). Real post-patch state: **0 HIGH, 2 residual MEDIUM, ~6 LOW**.

---

## Follow-up disposition after the counter-audit

> This section describes the fix prepared after the adverse counter-audit. It rewrites neither the evidence nor the historical conclusions of Claude above.

| Counter-audit finding | Follow-up disposition | Fix and non-regression evidence |
|---|---|---|
| Medium — leak in `extract_target` | **Fixed** | Every textual value of the target is now redacted independently then bounded to 512 characters. Credentials with or without a scheme and sensitive key names in camelCase are covered by adverse tests (`audit/redaction.py`, `tests/unit/test_audit_redaction.py`). |
| Medium — inherited `verify_tls=false` | **Fixed** | The deployment policy is re-evaluated before any verification of a new PAT and before decryption of the PAT used by a tool. An old value in the database therefore fails closed if the opt-in is no longer active (`forgejo_credential_service.py`, `forgejo_tool_service.py`, `tests/unit/test_production_hardening.py`). |
| Low — duplicated `X-Forwarded-For` lines | **Fixed** | All lines are merged with `Headers.getlist()` before the right-to-left resolution; trust remains limited to the declared proxy CIDRs. |
| Low — concurrent login/invitation bursts | **Fixed** | Every attempt is reserved atomically under a lock before authentication; a success releases only its own reservation. A concurrent test of 10 calls confirms that only 5 are accepted for a limit of 5. |
| Low — proxy headers of the standalone image | **Fixed** | The Dockerfile `CMD` now uses `--no-proxy-headers`, like the reference Compose file. |
| Low — dot segments in file paths | **Fixed** | The `.` and `..` segments are rejected both by the MCP schemas and by Forgejo client validation, including inside a path. |
| Low — schemeless credentials and camelCase keys | **Fixed** | Authorities of the form `user:secret@host/path`, `apiKey` and `privateKey` are redacted before persistence. |

### Final verdict after follow-up

- **Critical: 0** known finding.
- **High: 0** uncorrected.
- **Medium: 0** confirmed application defect left untreated within the scope of the counter-audit.
- The remaining limits are operational and documented: final DNS resolution for migrations by Forgejo, images/Actions not pinned by digest/SHA, single-process limiters, TLS termination and secret backup left to the operator.
- The OAuth `resource` relaxation remains a documented single-resource compatibility decision: a value that is present but incorrect is still rejected and no additional grant, tool or scope is granted.
- **Permissions:** no additional Forgejo PAT scope, MCP tool, MCP grant or GitHub permission was added.

### Historical branch validation at commit `e53b3fa`

- Python: **135 tests collected, 134 passed and 1 external E2E skipped**.
- Ruff check/format, MyPy strict, ESLint, TypeScript and the Vite build: pass.
- Docker E2E: the 50 tools, OAuth and MCP `2025-06-18` pass against Forgejo 16.0.2 and 16.0.3.
- PostgreSQL: OAuth migrations applied successfully on a fresh throwaway database.

---

## 🔁🔁 Second counter-audit — adverse verification of follow-up commit `e53b3fa` (2026-09-02, night)

> Note Claude — **adverse and independent** counter-verification of commit `e53b3fa`, conducted AFTER its publication (unlike the "Follow-up disposition" section above, which shipped in the commit itself). Witnesses executed through the project venv, including extraction of the code at `e53b3fa^` to prove the original defects by contrast; full diff re-read; pytest/ruff/mypy re-run by the auditor.

### Commit integrity: ✅ confirmed

- Full diff read: the 7 announced fixes are all present, all in the direction of hardening. **Nothing out of scope**: no `pyproject.toml`, no `uv.lock`, no `package-lock.json`, no new endpoint or feature, no suspicious code, no secret in the diff.
- Tests strengthened, not weakened: the only assertion removed ("`check()` does not allocate") is made obsolete by the new reservation design and replaced by a stronger check; the new tests are adverse (fakes proving that the PAT **is not sent** and **is not decrypted**, 10 threads → exactly 5 accepted, `must-not-reach-target` marker).
- Docs: the oversold sections of `38bde2d` are **requalified** as "before counter-audit", not erased — the history is preserved.
- Re-run by the auditor: `pytest tests/unit` → **126 passed**; 135 collected (matching the announcement); `ruff` and `mypy src` → 0 error. Git state: pushed to `origin/compat/forgejo-16.0.3`, clean working tree.

### Verdict per fix (witnesses executed)

| Finding from the 1st counter-audit | Adverse verdict |
|---|---|
| A — MED. raw `extract_target` | ✅ **CONFIRMED FIXED** — function identity proven (no dead copy), credential-bearing URL / encoded userinfo / schemeless authority → redacted, values bounded to 512, readable positive witness. Low residuals: a credential preceded by a `/` escapes the pattern; a password containing `@` without a scheme is partially redacted; **new false positives** on free text of the form `x:y@z` (`12:30@office` → redacted) — a loss of audit readability, not a leak. |
| B — MED. TLS guard at use time | ✅ **CONFIRMED FIXED** — `ConfigurationUnavailable` refusal **before** decryption (sentinel never reached) and **before** the PAT is sent, at both use points, symmetric with the allowlist; the flag does govern the passage (witnesses with/without). |
| C — LOW duplicated XFF | ✅ **CONFIRMED FIXED** — `getlist` + join; the spoof that won with `headers.get` (proven along the way) no longer wins. |
| D — LOW camelCase | ✅ **CONFIRMED FIXED** — `apiKey`/`privateKey`/`XApiKey`… redacted; battery of 32 real keys from the registry: **0 false positive**. |
| E — LOW login burst | ✅ **CONFIRMED FIXED** — atomic reservation with lease: old code 20/20 attempts passing (defect proven on `e53b3fa^`), new code exactly 5/20. Accepted change: more than 5 **valid** simultaneous logins for the same `ip:username` → 429 for the excess (marginal DoS inherent to reservation). |
| F — LOW Dockerfile + whitespace alignment | ⚠️ **PARTIAL** — `--no-proxy-headers` present ✓, `.` segments rejected by the client ✓, ASCII `" .. "` rejected by the schemas ✓, no legitimate value rejected ✓. **But** the schema lookahead only enumerates `[ \t\r\n]` whereas the client strips Unicode: `'\xa0..\xa0'`, `'　..'` still pass the schemas; and `_FILE_PATH` received no whitespace handling at all. **Exploitability nil** (the client remains strict and rejects everything — the misalignment is still in the permissive-schema/strict-client direction), but the claim that the two layers are aligned holds only for ASCII whitespace on owner/repo/ref. |

### Provenance reservations

- The "adverse counter-audit" of the preceding section and its closure are co-delivered in the same commit `e53b3fa`: its independence rests on the text, not on the git history. The present second counter-audit, by contrast, is subsequent to and external to the commit.
- Not re-proven locally by the auditor: the 50-tool Docker E2E, migrations on a throwaway database, ESLint/Vite build, post-commit Gitleaks/Bandit/pip-audit/npm audit rescans. Unit/ruff/mypy: confirmed.

### Final state after the second counter-audit

**0 CRITICAL, 0 HIGH, 0 residual application MEDIUM.** What remains: LOW/informational residuals (Unicode whitespace in the schema patterns and `_FILE_PATH` — defense in depth intact; residuals of the redaction pattern and its false positives on free text; possible 429s on a burst of valid logins) and the documented operational risks (migration DNS resolved by Forgejo, images by tag rather than digest, single-process limiters, TLS/backup left to the operator), plus the assumed product decision on the optional OAuth `resource`. The repository is in a solid security state for a self-hosted v0.1.0 behind a correctly configured TLS reverse proxy.

---

## Disposition after the second counter-audit

> This disposition was added after the second counter-audit was received. Its original text above is preserved in full.

| Confirmed low reservation | Disposition | Fix and witness |
|---|---|---|
| Schemeless authorities incompletely redacted | **Fixed** | The pattern now accepts a `/` prefix, consumes a password containing `@` up to the final authority, and requires a host/path form. Sensitive markers disappear from the audit while the ordinary text `12:30@office` remains unchanged. |
| Unicode whitespace around dot segments | **Fixed** | The owner/repository/ref schemas now use the Unicode `\s` class. The path schema also reproduces the client's global `strip()` for absolute paths and for leading or trailing `.`/`..` segments. Non-breaking and ideographic spaces are covered by the tests. |
| More than five valid simultaneous logins on the same key | **Accepted behavior** | Atomic reservation is the intended security property. Successes release their own lease; excess calls receive a temporary `429`, with no permission broadening and no secret persistence. |

### Verdict after closure

- **Critical: 0; High: 0; Application medium: 0.**
- The two low code residuals demonstrated by the second counter-audit are fixed and tested in both directions (secret neutralized, legitimate text preserved).
- What remains are the already documented operational constraints and the single-resource decision on OAuth `resource`; no PAT scope, tool, MCP grant or GitHub right is added.
- Python validation: **144 tests collected, 143 passed, 1 external E2E skipped**, after full migrations on a fresh PostgreSQL database.

---

## 🔁🔁🔁 Third counter-audit — range `e53b3fa..3851931` (2026-09-02/03)

> Note Claude — adverse and subsequent counter-verification of the 4 commits published after the second counter-audit: `b8860d8` (closure of the residuals), `aa8187a` (durable OAuth lifetimes), `6c5eed3` (tool-discovery performance), `3851931` (concurrent refresh recovery). Witnesses executed against the service's real code (33 measurements on the functional commits, exhaustive sweep of all 1,112,064 codepoints for schema alignment, RFC 9700 §4.14 downloaded and confronted with the text); full diff re-read commit by commit; pytest/ruff/mypy re-run (139 unit green, 148 collected).

### Range integrity: ✅ confirmed, 3 reservations on form

- No dependency touched, no suspicious code, no secret, single author, everything pushed (matching `ls-remote`). Deny-by-default preserved throughout.
- Only 2 outright assertions removed across the whole range, one replaced by a strengthened equivalent — but the anti-replay semantics were relaxed **in two notches spread across two commits** (aa8187a: rejection without revocation inside the grace window; 3851931: acceptance with issuance), invisible in the cumulative diff. Not concealed (CHANGELOG + OAUTH-005 rewritten + explicit residual risk), but the title of aa8187a ("lifetimes") does not announce the stepping stone.
- Reservations on form: secondary objects not announced by the commit messages (16.0.2→16.0.3 requalification in b8860d8, root `path=""` in 6c5eed3 — both in the CHANGELOG); **retroactive rewriting of validation figures in dated audit reports** (135/134 → 144/143 across 3 docs, themselves already stale at HEAD: 148 in reality) — a documentary record-keeping inconsistency, not falsification.

### Verdict per commit

| Commit | Verdict | Detail |
|---|---|---|
| `b8860d8` residuals | ⚠️ **1 fixed, 1 REFUTED** | **Unicode whitespace: genuinely fixed** — schema↔client alignment proven by exhaustive sweep (misaligned class **empty**; ZWSP/fullwidth/internal-segment residual accepted identically on both sides, literal, not exploitable at this boundary). **Redaction: closure REFUTED** — the original witness `dir/bot:ghp_leak@host/file` **still leaks** (the commit's test uses `/mirror-bot:…` at the head of the string, a form that sidesteps the finding); **regression introduced**: `user:secret@host` without a trailing slash used to be redacted and now leaks; `12:30@office/room` false positives retained. The "Fixed" disposition above is wrong on both of its halves as soon as the finding's witnesses are replayed. Suggested fix: boundary via non-consuming lookbehind `(?<![^\s(/])` + terminator `(?:/|$|\s)`. |
| `aa8187a` lifetimes | ✅ **SAFE (hardening), 2 reservations** | The refresh token moved from a **sliding** expiry (∞ for an active client) to an **absolute** bound chosen by the user at consent time (1/7/30/90 d, hard cap 90, double server-side validation), inherited at every rotation (0 s drift at the witness), access bounded to min(1 h, grant), no silent re-auth, fail-closed migration. Reservations: **dashboard revocation does not cut the grant** (proven: the client re-refreshes and access returns — only user suspension, credential revocation and client-side `/revoke` cut the family), while the consent page promises "revoke at any time"; and the commit quietly introduces the 10 s grace window (notch 1 of the relaxation). |
| `6c5eed3` perf | ✅ **SAFE** | No cache, no memoization: one DB snapshot per request, both listing AND execution re-read the database (the "selector verified, execution optimized" pitfall does not exist here). Witness on the 5 revocation levers: **immediate DENY, no staleness window**. Removal of `_sync_registry` from the hot path has no effect (missing line = disabled, fail-closed intact). `path=""` locked by `oneOf const ""` on the listing tool only. |
| `3851931` concurrent refresh | 🟠 **AT RISK — controlled regression of theft detection** | Within the grace window (10 s default, max 60), an **already-rotated** refresh emits an **independent pair** instead of being rejected. Proven by execution: a stolen token replayed ≤ 10 s after the legitimate rotation **forks a durable branch** — attacker and client both keep valid tokens up to the grant bound (≤ 90 d), **unlimited** replays within the window (4 branches at the witness), zero revocation, only `oauth.concurrent_refresh_recovered` events **without family_id or user_id** (the prescribed review is barely actionable). The RFC 9700 §4.14.2 property ("double use informs the server of the compromise") is voided **within the window**; outside the window, family revocation holds (including forked branches, proven); `grace=0` restores strictness (proven). Mitigating factors: narrow exploitation window, scope/client/revocation verified before issuance, risk documented as residual. |

### Findings open after the third counter-audit

1. 🟠 **MEDIUM** — undetected fork within the refresh grace window (`oauth_service.py:450-475`): make the response **idempotent** (re-serve the pair from the first rotation — forcing both holders onto the same chain, hence detection at the next rotation) or cap it at one recovery per token; at minimum enrich the event (`family_id`, `user_id`) and document `FMCP_OAUTH_REFRESH_TOKEN_REUSE_GRACE_SECONDS=0` as the hardened profile.
2. 🟠 **MEDIUM** — dashboard revocation of an OAuth token does not revoke the **family**: the client re-refreshes and comes back. Contradicts the governance promise ("Revocable access") and the consent page. Revoke the family from the dashboard, or expose an "OAuth authorizations" view.
3. 🟡 LOW — redaction pattern: original witness still leaking + slashless regression + false positives (persisted audit layer only).
4. 🟡 LOW (form) — documentary record-keeping: figures in dated reports rewritten retroactively and already stale; closure dispositions co-delivered in the very commit they close (pattern repeated despite the reservation raised in the previous round).

### State after the third counter-audit

**0 CRITICAL, 0 HIGH, 2 MEDIUM reopened** (grace-window fork, missing family revocation at the dashboard) **+ 2 LOW**. The foundation remains solid — the real hardening work (absolute grant bounds, tool discovery without staleness, exhaustively proven Unicode alignment) is confirmed by execution. But the trajectory calls for vigilance: two claimed closures have now been refuted by the original witnesses (redaction in the 2nd round as in the 3rd), and the anti-replay relaxation arrived in two half-steps under titles that did not announce it. Future dispositions should be verified against the findings' witnesses, not against neighboring variants.

---

## Disposition after the third counter-audit

> This disposition is subsequent to the third counter-audit. It modifies neither its evidence, nor its conclusions, nor the historical figures of the earlier validations.

| Third counter-audit finding | Disposition | Fix and witness |
|---|---|---|
| Medium — durable branches on concurrent refresh | **Fixed** | The first rotation keeps its pair in memory for the configured grace window. A duplicate within the same process receives exactly that pair; a missing entry fails closed without creating a branch and without revoking the healthy rotation. After the grace window, reuse still revokes the entire family. The PostgreSQL and Docker tests replay concurrent refreshes and verify that both responses are identical. |
| Medium — incomplete Dashboard revocation | **Fixed** | Revoking an OAuth access token from the user or administrator Dashboard atomically resolves then revokes every refresh and access token known to its family. The PostgreSQL and Docker tests prove that the access token and the refresh are subsequently refused. |
| Low — redaction of schemeless authorities | **Fixed** | The exact witnesses `dir/bot:ghp_leak@host/file` and `user:secret@host` are neutralized. The ordinary text `12:30@office/room` remains readable. The witnesses are covered both in the recursive redaction and in `extract_target`. |
| Low — historical figures rewritten | **Fixed** | The results of earlier validations are restored to their values at the commit concerned. The current state is recorded only below, without rewriting the historical sections. |

### Current validation after closure

- Python without PostgreSQL: **140 passed and 9 skipped**.
- Python with PostgreSQL: **149 collected, 148 passed and 1 E2E requiring external credentials skipped**.
- Ruff check/format and MyPy strict: pass.
- ESLint, TypeScript and the Vite build: pass.
- Alembic migrations on a fresh PostgreSQL database: pass.
- Docker E2E Forgejo 16.0.2 and 16.0.3: 90-day OAuth, idempotent refresh recovery, family revocation from the Dashboard, MCP `2025-06-18` and the 50 tools all pass.
- Permissions: no additional Forgejo PAT scope, MCP tool, MCP grant or GitHub right.

### Current verdict

- **Critical: 0; High: 0; Application medium: 0** known finding remaining within the scope of the three counter-audits.
- The residual constraints remain operational and documented: single-process recovery cache and limiters, final DNS resolution for migrations by Forgejo, images/Actions not pinned by digest/SHA, TLS termination and backups under operator responsibility.
- Multi-replica deployment is not supported. A duplicate without a recovery entry, notably after a restart or on another process, fails closed and requires a new refresh with the current pair.

---

## Upstream maintainer review of commit `cf40e9b` — 2026-09-08

> This section is subsequent to the Claude audits above. It preserves their historical verdicts while recording the two technical blockers reproduced by the upstream maintainer and verified locally.

The maintainer asked that the monolithic contribution be replaced by three independent Pull Requests: Forgejo 16.0.3 compatibility, hardening/deployment, then OAuth/migrations. The request is well founded: the diff of `cf40e9b` did in fact mix these three scopes and prevented independent review of the risks.

| Reproduced blocker | Severity | Evidence | Disposition |
|---|---|---|---|
| Double decoding of compressed Forgejo responses | Functional blocker | HTTPX decodes `gzip`/`deflate` during `aiter_bytes()`, and the reconstruction then kept `Content-Encoding` and re-triggered the decoder. Both witnesses failed with `httpx.DecodingError`. | **Fixed and tested**: removal of the encoding and wire-length headers after the decompressed size has been checked; the `gzip` and `deflate` tests pass. |
| Concurrent refresh rotation with family revocation | **High** | A PostgreSQL revocation blocked on the current refresh kept a snapshot that did not contain the replacement committed afterwards. After the revocation, the new access token remained authenticable. | **Fixed and tested**: one persisted row per family, transactional lock shared by rotation and by every revocation, refusal if the family is absent/revoked, migration repairing historically partial families. The test waits for real PostgreSQL contention and proves that the replacement is unusable. |

The operational documentation now distinguishes OAuth discovery, DCR, login/consent and token exchange. It also records the observed diagnosis in which an existing Claude registration kept working while a new OpenAI/Codex DCR was blocked by a Cloudflare bot check before reaching the application. No production hostname, IP address, token, invitation, account identifier or request identifier is published. Allowlists by cloud IP or `User-Agent` are not recommended.

### Validation after these two fixes

- Python without PostgreSQL: **142 passed and 10 skipped**.
- Python with PostgreSQL: **152 collected, 151 passed and 1 E2E requiring external credentials skipped**.
- Race test before the fix: failure demonstrated, the replacement remained valid.
- Same test after the fix: passed, with PostgreSQL lock contention observed.
- Alembic migration `20260908_0011`: upgrade, downgrade to `20260902_0010`, then re-upgrade all succeeded.
- Ruff check/format and MyPy strict: pass.
- No additional Forgejo PAT scope, MCP tool, MCP grant or GitHub right.

The two Docker E2E suites were then replayed with the fixes: Forgejo 16.0.3 as the minimum supported version and Forgejo 16.0.2 as the comparative reference both pass OAuth, MCP `2025-06-18` and the 50 tools. The Swagger comparison still shows exactly 2 structural differences and 0 endpoint difference.

---

## 🔁🔁🔁🔁 Fourth counter-audit — range `3851931..b40124c` (2026-09-08)

> Note Claude — adverse and subsequent counter-verification of the 4 commits `cf40e9b` (closure of the 3rd counter-audit), `4d85fcd` (compressed decoding), `6dd04a5` (serialization of family revocation), `b40124c` (docs). Witnesses executed against the **real service on real PostgreSQL migrated by Alembic** (not SQLite: `FOR UPDATE` and migration `0011` are genuinely exercised), `tracemalloc` memory measurements on real httpx, full diff re-read, pytest/ruff/mypy/alembic re-run. No source file modified.

### 🛑 Publication state

`git ls-remote origin` is authoritative: the remote branch and **upstream PR #3 (kepatrick/forgejo-mcp, OPEN)** are at **`cf40e9b`**. The 3 commits `4d85fcd`, `6dd04a5`, `b40124c` are **unpushed** (same author second: batch created in one go). Consequence: the public PR still carries the **HIGH** regression acknowledged by the maintainer (refresh replacement surviving family revocation), whose fix exists only locally. The maintainer's request to split into 3 PRs is acquiesced to in writing but not carried out; the local batch further weighs the single PR down with a migration.

### Range integrity: ✅ confirmed

Nothing out of scope, no dependency/CI/Docker touched, no network/execution code added, no secret (instrument validated on a positive witness 3/3), single author. 4 modified assertions = announced design inversions (idempotent recovery), no test deleted, and the 3rd round's original witnesses are this time **replayed verbatim** in the suite. Re-run: **142 unit passed**, 152 collected, ruff/mypy green, `alembic heads` = `0011` single head.

### Verdict per 3rd counter-audit finding (original witnesses replayed)

| Finding | Adverse verdict |
|---|---|
| 1 — MED. undetected fork within the grace window | ✅ **FIXED — as of `6dd04a5`, not `cf40e9b`**. **Idempotent** recovery proven: 4 replays of R0 within the grace window → a single pair, 0 branch; both holders forced onto the same chain, second use at the next rotation → **family revoked, bearer refused** (RFC 9700 §4.14.2 restored); outside the grace window and with `grace=0` → strict; cold cache (another process) → rejection without revocation; 2 simultaneous refreshes → identical responses. Event enriched with `family_id`/`user_id`/`refresh_token_id`/`cache_hit`. Minor reservation: the hot-cache path does not go back through `_require_authorizable_user` — a pair is served to a user disabled in the meantime (without effective access: the bearer is refused; audit noise). |
| 2 — MED. dashboard revocation without family | ⚠️ **FIXED going forward, PARTIAL for existing data.** Post-migration: dashboard revocation → family revoked, bearer refused, refresh `LOAD_NONE`, replay within the grace window `LOAD_NONE` ✅; admin/suspension/`/revoke` all cut ✅. **But migration `0011` only re-reads `oauth_refresh_tokens.revoked_at`**: a dashboard revocation performed **before the update** (which touched only `mcp_tokens`) is ignored — proven on inherited data seeded at `0010`: family "F_dash_legacy" → `revoked_at=None`, **refresh OK, new pair issued, bearer accepted**. Exactly the finding's scenario, for everything users believed already revoked. Fix: propagate `mcp_tokens.revoked_at` (join on `mcp_token_id`, `kind='oauth'`) into the migration's `MIN`. Note: revoking the Forgejo credential cuts **no** family (the bearer accepts the access token until expiry ≤ 1 h; only tool execution fails) — the 3rd round wrongly filed it among the cutting levers. |
| 3 — LOW redaction pattern | ⚠️ **PARTIAL, with a regression.** `dir/bot:ghp_leak@host/file` and `user:secret@host` now redacted ✅, `12:30@office/room` intact ✅. But `git clone bot:ghp_secret@example.test:o/r.git` **still leaks** (a non-numeric port fails `_AUTHORITY_HOST`), `release:v2@stable/notes` remains a false positive, and there is a **new regression**: `1234:5678@host/r` (numeric user and password — PINs, ids) **leaks**, because of the `isdecimal()` clause added to save `12:30@office`. One false positive traded for one leak. Persisted audit layer only: severity LOW unchanged. |
| 4 — LOW documentary record-keeping | ⚠️ **PARTIAL.** `cf40e9b` honestly restores the historical figures (144/143 → 135/134, verified against `git show e53b3fa`) and relabels the dated sections as "historical" (clarifying, not falsifying, but not "append only" either). The pattern of **co-delivering the disposition and the fix in the same commit** is **repeated** in `cf40e9b` despite the previous round's reservation. `b40124c`: pure addition. |

### Functional commits

| Commit | Verdict |
|---|---|
| `4d85fcd` compressed decoding | ✅ **SAFE** — fixes a **total outage** (100 % of Forgejo calls in `DecodingError` behind any reverse proxy that compresses, because `aiter_bytes()` already decodes and the reconstruction re-triggered the decoder), fail-closed. 50 KiB gzip witness: REJECT before, ACCEPT decoded once after. |
| `6dd04a5` family serialization | ✅ **SAFE** — `SELECT … FOR UPDATE` on `oauth_token_families`, **identical** acquisition order on all 3 paths (refresh, `/revoke`, dashboard) → no deadlock (measured: serialized wait 0.5 s, correct outcome); refresh/revocation TOCTOU **closed** (READ COMMITTED + lock held until commit). **`mcp_bearer.py`**: diff = 3 lines, every prior link intact, `family is None` ⇒ **fail-closed refusal** (orphan with FK removed → REFUSE, revoked family → REFUSE, static with a link → REFUSE). The bearer never takes the family lock (auth in 9 ms while a `FOR UPDATE` is held). |
| Migration `0011` | ✅ **SAFE** — backfill before FK, no `NOT NULL` without a default, transactional DDL, upgrade/downgrade/re-upgrade measured idempotent, "pre-0011 race" families closed at migration time, clean downgrade (it is `0009` that purges `kind='oauth'`, unchanged). Only gap: the F_dash_legacy case above. |

### 🆕 New findings (one of which refutes the 1st audit)

1. 🟠 **MEDIUM — decompression bomb: the 10 MiB cap does not protect against compressed bodies.** The initial audit (§5, "responses bounded to 10 MB streamed before buffering") was **wrong for this class**: the cap applies to decompressed bytes but is only checked **after** httpx has inflated an entire raw chunk (`READ_NUM_BYTES` 64 KiB, `decompressobj().decompress()` without `max_length`), and chained encodings are accepted without limit. Measured (`tracemalloc`, 64 KiB chunks): `gzip` 100 MiB → 142 MiB allocated; `gzip,gzip` (335 B on the wire) → 210 MiB; **`gzip,gzip,gzip` 512 MiB (245 B on the wire) → 1.07 GiB allocated, RSS 2.1 GiB** before the refusal. Pre-existing, identical before and after `4d85fcd`. Reachable from a compromised Forgejo or from a MITM if `verify_tls=false`. `br`/`zstd`: decoders absent from the venv → identity → fail-closed; would worsen if `httpx[brotli]` were installed. Fix: `Accept-Encoding: identity` + refusal of any `Content-Encoding`, or bounded `aiter_raw()` on the wire plus manual decoding with `max_length`/`unconsumed_tail`, and refusal of multi-valued `Content-Encoding`. |
2. 🟡 LOW (pre-existing) — **a request accepted during an open revocation transaction**: the bearer finishes its checks then blocks on `UPDATE mcp_tokens SET last_used_at` (row lock held by the revocation); when the latter commits, the already validated request is **accepted** (re-auth → refused). Window = the duration of the revocation transaction, unbounded (no `lock_timeout`/`statement_timeout`). Fix: `UPDATE … WHERE enabled AND revoked_at IS NULL` + `rowcount != 1` ⇒ refusal.
3. 🟡 LOW — `revoke_oauth_family` on a missing family returns `()` **without revoking anything** while `revoke_token` logs `oauth.token_family_revoked` (misleading audit). Unreachable after the migration (NOT NULL + FK); should be hardened into an explicit failure.
4. 🟡 LOW — `grace=0` strict: guard coded (`grace_seconds > 0 and …`), **no dedicated test** in the suite, neither before nor after (the proof in rounds 3 and 4 is an auditor's witness).

### State after the fourth counter-audit

| | |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 in the local tree — **1 on the public PR** (`cf40e9b`, rotation/revocation regression acknowledged by the maintainer, fix unpushed) |
| MEDIUM | 2: decompression bomb (pre-existing, refutes the 1st audit); migration `0011` ignoring earlier dashboard revocations |
| LOW | ~6: redaction (scp-like, `1234:5678@`, false positive), request accepted during an open revocation, silent no-op, `grace=0` without a test, pair served to a disabled user, disposition/fix co-delivery |

**Priority actions**: (1) **push** `4d85fcd`+`6dd04a5` or withdraw the PR from review while the HIGH is on it; (2) bound decompression on the wire; (3) complete the `0011` backfill with `mcp_tokens.revoked_at`; (4) split into 3 PRs as the maintainer asked. The OAuth foundation is now genuinely RFC 9700-compliant within the grace window, and the bearer remains fail-closed on every path tested — but two more "Fixed" closures turned out to be partial when the original witnesses were replayed, and one claim from the first external audit (my own) has fallen: a "capped before buffering" claim is measured with a compressed body, not only with a cleartext one.

---

## 🔁🔁🔁🔁🔁 Fifth counter-audit — range `b40124c..e0f8852` (2026-09-08, evening)

> Note Claude — adverse counter-verification of the 4 commits `081e254` (decompression bound), `26fc722` (migration `0012`, inherited dashboard revocations), `44137c0` (redaction), `e0f8852` (docs `adverse-audit-followup-2026-09-08.md`). Witnesses replayed on the **real streaming path** (`aiter_raw` stream AND a real local HTTP server via httpcore — the maintainer rightly points out that preloaded transports are outside the boundary), throwaway PostgreSQL 16 for the migration with 13 families seeded at `0010`, 26+ redaction witnesses. Integrity: `/usr/bin/git`, authenticated `gh pr view`. No source file modified.

### 🛑 Publication — unchanged, worse

`ls-remote` and `gh pr view 3` agree: **PR #3 still at `cf40e9b`**, now **7 unpushed commits** (batch scripted in 2 s). **The HIGH acknowledged by the maintainer remains on the public PR.** The follow-up document elides this point ("must be verified separately") instead of naming it. Pushed as-is, the single PR would now carry two migrations (`0011`, `0012`) that the maintainer had asked to isolate.

### Integrity: ✅ confirmed

Scope matches the commit messages, nothing off topic, no dependency/CI/Docker touched, no suspicious code, **zero assertion or test deleted**, no secret (instrument validated 4/4), docs are pure additions, **disposition/fix co-delivery finally separated** (distinct docs commit). Re-run: **151 unit passed**, 162 collected, ruff/mypy green, `alembic heads` = `0012` single. Not verifiable here: "161 passed" with PostgreSQL.

### Verdict per 4th counter-audit finding

| Finding | Adverse verdict |
|---|---|
| A — MED. decompression bomb | ✅ **FIXED.** The client reads `aiter_raw` and decodes itself with `max_length`; chained encodings are refused **before any decoding**: `gzip,gzip,gzip` 512 MiB (243 B on the wire) → peak **0.01 MiB** on the stream / 0.28 MiB on the real server (against 1.07 GiB in the 4th round); gzip 100 MiB → 20.2 MiB (≈ 2 × the cap plus a chunk, the ×2 being the zlib output buffer), identical on the real server; `br`/`zstd`/`x-gzip` → refused; lying header → refused; lying `Content-Length` → refused. Positive witnesses: 9.9 MiB from 10 KiB of gzip → ACCEPT, **byte-for-byte identical**; exactly 10 MiB → ACCEPT; 10 MiB + 1 → REJECT; no silent truncation (`unconsumed_tail` never non-empty before `MAX+1`). Single HTTP exit point verified (`client.stream` → `_bounded_response`). Preloaded transport: 209 MiB already allocated in `Response.__init__` before the final size refusal — outside the boundary, documented, no effect in production (the httpx transport streams). **Price paid in availability (fail-closed)**: raw deflate without a zlib header is now refused; multi-member gzip (`cat a.gz b.gz`) refused (httpx only decoded the first member anyway — the old behavior was itself wrong); **empty body + `Content-Encoding: gzip` → "Truncated"** whereas 5 endpoints expect a 204 — a reverse proxy that sets the header on a 204 breaks them. The maintainer's test (1 MiB / 16 MiB, `peak < 5×`) is a genuine bounded witness but single-layer; the chained bomb is covered only by `not is_stream_consumed` (a stronger assertion, but a variant). |
| B — MED. migration `0011` ignoring earlier dashboard revocations | ✅ **FIXED, no over-revocation.** 13 families seeded at `0010`, upgraded to `0011` (the `F_dash_legacy*` stay `None`, as in the 4th round) then to `0012`, then the **real service** (bearer + refresh): F_dash_legacy (with or without audit), F_dash_legacy_rotated (audit present, R1/M1 alive → whole family cut), F_partial → **REVOKED, bearer and refresh refused**; F_alive (healthy rotation) → intact, refresh OK; F_static → untouched; a false positive was looked for and not found (the `mcp_token.revoked` action is written only by the dashboard, never by rotation). Idempotent ×2 (md5 of the 4 tables identical), documented no-op downgrade, single head. **Documented residual under-revocation**: F_dash_legacy_rotated_**noaudit** (dashboard revocation followed by a rotation, audit absent) is indistinguishable from a healthy rotation → it stays alive; there is no audit-purging code in `src/`, so it is reachable only by manual deletion in the database. Reservation: the maintainer's test is a **variant** (reduced ad hoc tables, without the real Alembic schema or the service, skipped without PostgreSQL) — the proof above is the auditor's. |
| C — LOW redaction | ⚠️ **PARTIAL — original leaks closed, two regressions.** Closed: `git clone bot:ghp_secret@example.test:o/r.git`, `git:ghp_x@github.com:o/r.git`, `1234:5678@host/r`, `0000:1234@10.0.0.1/x`, `bot:pa/ss@host/r`, parentheses/quotes/trailing period, `24:00@`/`12:60@` (12 leaks). Intact: `12:30@office`, `meeting 12:30@office/room`, `user@example.com`, `git@github.com:o/r.git`, `time 09:45@site/log`. **Leak regression**: `bot:ghp(leak)@host/r` used to be redacted and **now leaks** (parentheses removed from the authority character set). **False-positive regression**: `ratio 1:2@scale` used to be intact, now redacted (the `isdecimal` exemption replaced by strict HH:MM). Not fixed and acknowledged: `release:v2@stable/notes`. Terminators still open (pre-existing): `, ; [ ] < > ? #`. Persisted audit layer only; severity LOW unchanged. |

### Fate of the 7 residuals from the 4th round

| Residual | Actual disposition |
|---|---|
| (a) bearer request accepted during an open revocation | **Declared open** by the maintainer, not addressed |
| (b) `revoke_oauth_family` silent no-op + misleading audit | **Passed over in silence** |
| (c) `grace=0` without a dedicated test | **Passed over in silence** (no test added) |
| (d) pair served to a disabled user (hot cache) | **Declared open**, not addressed |
| (e) unpushed commits / HIGH on the PR | **Elided** (neither quantified nor named) — 7 unpushed |
| (f) split into 3 PRs | **Declared open**, not done |
| (g) disposition/fix co-delivery | ✅ **Addressed** (separate docs commit) |

### State after the fifth counter-audit

| | |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 in the local tree — **1 on the public PR** (unchanged since the 4th round) |
| MEDIUM | **0** residual application medium (both from the 4th round genuinely fixed, proven on the real path and on real PostgreSQL) |
| LOW | ~8: redaction (2 regressions + 1 acknowledged false positive + terminators), (a) (b) (c) (d), empty 204 + gzip header breaking 5 endpoints, under-revocation without audit |

**Priority actions**: (1) **push** — or withdraw the PR from review: this is the only HIGH and it depends on no code at all; (2) address residuals (a) and (b) (a few lines each: `UPDATE … WHERE revoked_at IS NULL` + rowcount; explicit failure on a missing family); (3) tolerate an empty body with `Content-Encoding` on 204s; (4) add the `grace=0` test; (5) split into 3 PRs. The local code is now at the level the first audit already believed it had reached — but it is not where the reviewers are looking.

---

## 🎯 Initial audit verdict, kept for the historical record

**No malware, no backdoor, no booby-trapped dependency.** Professionally crafted code, a deliberately fail-closed architecture, and most of the security claims verified in the code.

However: **2 HIGH flaws** (one of which **refutes the self-audit shipped in the repository**), **5 MEDIUM**, about a dozen LOW — to be addressed before use in critical production.

### Summary table

| # | Severity | Finding | Location |
|---|---|---|---|
| 1 | 🔴 **HIGH** | Traversal via `.`/`..` dot segments in `owner`/`repo`/refs → a tool grant no longer bounds the API endpoint actually called | `forgejo/client.py:2257-2266, 2232-2240, 1743-1746`; `tools/registry.py:89-90` |
| 2 | 🔴 **HIGH** | Empty Forgejo URL allowlist = everything permitted outside production → instance re-pointing and PAT exfiltration | `config.py:125-133` |
| 3 | 🟠 MEDIUM | Rate limiting keyed on the direct IP, ineffective/DoS-able behind a reverse proxy (the normal production deployment) | `api/auth.py:105-107`, `api/oauth.py:78,208`, `api/invitations.py:34-36` |
| 4 | 🟠 MEDIUM | Credential embedded in `clone_addr` persisted **in cleartext in the audit before** being rejected by validation | `mcp/server.py:182-196`, `audit/redaction.py`, `forgejo/client.py:2115-2118` |
| 5 | 🟠 MEDIUM | Committed file contents archived up to 4 KB per field in the audit (a committed `.env` leaves its secrets there) | `audit/redaction.py:51-53` |
| 6 | 🟠 MEDIUM | `verify_tls=false` freely enabled by the admin, with no deployment flag (inconsistent with cleartext HTTP) | `api/forgejo_instance.py:16` |
| 7 | 🟠 MEDIUM | Anti-SSRF migration guard without DNS resolution + Docker images pinned by mutable tag + container on `0.0.0.0:8000` without enforced TLS | `forgejo/client.py:2104-2141`, `deploy/Dockerfile`, `deploy/compose.yaml:50-52` |
| 8-17 | 🟡 LOW | See the detailed sections | — |

---

## 1. 🧬 Malware / supply-chain — CLEAN

### Python code (src/, scripts/, migrations/, tests/)

- **eval/exec/compile/\_\_import\_\_/marshal/pickle**: no occurrence.
- **dynamic getattr**: a single one (`application/forgejo_tool_service.py:379`), internal dispatch to the client's methods, with names coming from the hard-coded registry. Benign.
- **base64**: only for encoding file contents (Forgejo API), the encryption key, and PKCE in the tests. Never followed by execution.
- **subprocess**: a single use (`tests/e2e/full_docker_flow.py:937`), the local E2E bench. Legitimate.
- **sockets**: `socket.getaddrinfo` in `oauth_service.py:870-874` is an **anti-SSRF guard** (rejection of non-global addresses), not exfiltration.
- No access to `~/.ssh` or `~/.aws`, no direct `os.environ` in `src/` (pydantic-settings config with the `FMCP_` prefix), no write outside the project.

### Hard-coded domains / IPs — exhaustive list

| Domain/IP | Locations | Assessment |
|---|---|---|
| `127.0.0.1` / `localhost` / `0.0.0.0` | config, vite.config.ts, scripts, compose | ✅ local defaults/binds |
| `*.test`, `attacker.example`, `93.184.216.34` | tests | ✅ fixtures (reserved TLD, adverse SSRF tests) |
| `claude.ai` | OAuth tests | ✅ CIMD fixture |
| `git.company.internal`, `forge-mcp.example.com` | UI / .env.example | ✅ placeholders |
| `data.forgejo.org/forgejo/...` | compose, CI | ✅ official Forgejo registry |

**No** third-party domain or IP in production code. No exfiltration endpoint.

### Hooks, dependencies, CI, binaries

- `pyproject.toml`: standard hatchling build, no hook. `package.json`: no pre/postinstall.
- All dependencies are mainstream (fastapi, httpx, sqlalchemy, mcp, cryptography, argon2-cffi…). `uv.lock` is **100 % pypi.org**; `package-lock.json` **100 % registry.npmjs.org**. No typosquat, no git/tarball URL.
- `deploy/entrypoint.sh`: secrets copied at 0400 into a 0700 directory then privileges dropped with `setpriv`. No network, no `curl|sh`.
- CI: no `pull_request_target`, no secret used, `permissions: contents: read`.
- The only non-text tracked file is `py.typed` (empty, PEP 561). `.pyc` and `frontend/dist` are present on disk but **not versioned**.
- No obfuscation: no hex/base64 blobs, no homoglyphs; a single frontend `fetch`, `same-origin`.

### Git provenance

- `origin` designates the working fork; `upstream` = `github.com/kepatrick/forgejo-mcp.git` (original author, 2026-08-04 release).
- 6 unpushed local commits (OAuth 2.1 + hardening) + **6 modified uncommitted files**: they make the RFC 8707 `resource` parameter optional (resolved to the single configured resource) + restrict the CORSMiddleware. RFC-compliant, not malicious — to be reviewed before commit.

> ℹ️ Informational findings: GitHub actions pinned by tag (`@v5`) rather than by SHA; local artifacts (`__pycache__`, `frontend/dist`) to be cleaned before redistribution.

---

## 2. 🔴 The two HIGH flaws

### HIGH #1 — Dot-segment traversal: the tool grant no longer bounds the endpoint

`_repository_name` (`client.py:2257-2266`) and `_ref_value` (`client.py:2232-2240`) accept `.` and `..` (only `/`, control characters and length are rejected). `quote(safe="")` does not encode them (`.` is "safe"), and **httpx 0.28.1 normalizes dot segments before sending** — verified by execution in the project venv:

```
httpx.URL('https://h/api/v1/repos/o/r/git/commits/..') → https://h/api/v1/repos/o/r/git
```

**Scenario**: an MCP token holding only `forgejo_get_repository` calls the tool with `owner="..", repo="user"` → the actual request is `GET {base}/api/v1/user` (the full profile, e-mail included), an endpoint that the permission model reserved for `forgejo_get_current_user`. Likewise `get_commit(sha="..")` → `GET .../repos/o/r/git`, `get_commit_status(ref="..")` → `GET .../repos/o/r/status`. Grant granularity is bypassed, and **the audit logs the supplied target, not the URL reached**.

**Real mitigations** (bounding the severity): same HTTP method, same PAT of the same user (no principal escalation), strict Pydantic parsing of responses which breaks exfiltration in most cases, redirects refused.

**⚠️ Refutes the repository self-audit**: `security-audit-2026-08-31.md` states "Path traversal: no exploitable traversal found; repository paths reject `..`" — the `..` rule exists only for *file* paths (`_file_path`), not for owner/repo/refs. It also contradicts `docs/security/organization-repository-creation.md:11` ("validated as one bounded path segment").

**Fix** (a few lines): reject `value in {".", ".."}` in `_repository_name` and `_ref_value`, fix the `^[^/\x00-\x1f\x7f]+$` pattern at `registry.py:89-90`, with a witness test on `owner=".."`.

### HIGH #2 — Empty allowlist = PAT exfiltration possible outside production

```python
# config.py:125-133
if not self.forgejo_allowed_base_urls:
    return True
```

`forgejo_credential_service.py:92-97` sends the PAT in cleartext to `instance.base_url`. The allowlist is mandatory only when `environment=production` (`config.py:91-92`). **Scenario**: a deployment launched outside compose in dev/staging mode and exposed to the network → a compromised admin (or residual XSS/CSRF on an admin session) re-points the instance to a server they control; at the next `PUT /api/me/credential` or `POST /test` of each user, their PAT arrives in cleartext at the attacker's. This is exactly the SEC-001 scenario the project claims to have closed — reopened outside production.

**Mitigations**: compose makes the allowlist mandatory (`:?set`), HTTP refused by default. **Fix**: reject an empty allowlist outside production too, or at the very least emit a loud warning at startup; consider gating `verify_tls=false` behind a deployment flag as HTTP is.

---

## 3. 🔐 Auth / OAuth 2.1 — remarkably solid

### Strong points verified in the code

- **Mandatory PKCE, S256 only** (`oauth_service.py:64,173`); **exact-match redirect_uri** (HTTPS/loopback registration only, re-compared between `/authorize` and `/token`); no open redirect found.
- **Single-use codes + anti-race**: `consumed_at` + `SELECT … FOR UPDATE` (`oauth_service.py:349-367`), TTL 60-600 s.
- **Refresh token rotation + replay detection**: any reuse **revokes the entire family** including access tokens (`oauth_service.py:425-428`, `_revoke_family:620`).
- **RFC 8707 binding everywhere**: authorization, exchange, refresh, bearer (`mcp_bearer.py:72`), with `hmac.compare_digest`.
- Consent: 256-bit opaque token, hashed, double CSRF (`SameSite=strict` cookie + strict Origin), HTML `escape()`d, **admins excluded from the OAuth flow**.
- Migration `20260902_0009` deletes `kind='oauth'` tokens on **downgrade** so that they do not turn back into static bearers — a rare and excellent reflex.
- **Tokens**: exclusively `secrets.token_urlsafe(32)`, stored **SHA-256 hashed**, compared with `hmac.compare_digest` and fail-closed if ≠ 1 candidate (`mcp_bearer.py:48-54`); revocation checked at every authentication AND every tool decision; DB constraint `ck_mcp_tokens_enabled_lifecycle`.
- **Sessions**: HttpOnly/Secure/`SameSite=strict` cookies, no fixation (tokens regenerated at login), CSRF bound to the session (double-submit + hash), a password change revokes the other sessions.
- **Passwords**: Argon2id (OWASP defaults), **near-constant-time login** (verify against a dummy hash if the account does not exist) — no timing enumeration.
- **Privilege escalation: nothing exploitable.** Admin bootstrap only when no admin exists, `must_change_password` blocking everywhere; invitations admin-only, role frozen to `USER`, single-use under `FOR UPDATE`; **no orphan endpoint** missing the auth dependency; **no IDOR** (all "me" resources scoped by user_id); token grants ⊆ user allowance, allowance modifiable by an admin only.

### Findings

| Severity | Finding | Location |
|---|---|---|
| 🟠 MEDIUM | **Rate limiting keyed on `request.client.host` with no proxy handling.** Behind a reverse proxy (normal production), all requests share the proxy's IP: (a) lockout DoS — login key `ip:username` → anyone can lock out any username (5 failures / 5 min); (b) DCR limits (10/h) and invitation limits become global → onboarding DoS. Conversely, `--proxy-headers` without an allowlist would make `X-Forwarded-For` spoofable. | `api/auth.py:105-107`, `api/oauth.py:78,208`, `api/invitations.py:34-36` |
| 🟡→🟠 | In-memory limiters with unbounded growth (`check()` creates an entry per probed key, never purged) + reset on restart, no persistent lockout | `auth/rate_limit.py:14-28,43` |
| 🟡 LOW | Replaying a consumed code does not revoke the already issued tokens (RFC 9700 recommends it) | `oauth_service.py:355-361` |
| 🟡 LOW | Perpetual static MCP tokens are possible (`expires_at` nullable) — a configurable max TTL is suggested | `mcp_token_service.py:50` |
| 🟡 LOW | Non-constant-time PKCE comparison (vendored MCP SDK; exploitation impractical) | SDK `handlers/token.py:178` |
| 🟡 LOW | DNS TOCTOU (rebinding) on the CIMD fetch, mitigated by the admin allowlist | `oauth_service.py:720-744` |
| 🟡 LOW | Password policy = length ≥ 12 only (no HIBP list) | `auth/passwords.py:14-16` |
| 🟡 LOW | No session idle timeout; `last_seen_at` frozen at login (misleading freshness in `/api/auth/sessions`) | `auth/session.py`, `auth_service.py:61-69` |

---

## 4. 🔑 Crypto / credentials

### Strong points verified line by line

- **AES-256-GCM** with a key required to be exactly 32 bytes, a **random 96-bit nonce per encryption** (`os.urandom`), **AAD binding ciphertext↔user↔key version** (`forgejo-credential:{user_id}:v{key_version}`) — preventing cross-user replay. **No hard-coded key, no fallback**: key missing → `CredentialKeyError` → HTTP 503, **fail-closed**.
- **The PAT is never returned to the client** (`CredentialResponse` = id/status/usernames/dates); the admin can only DELETE. Revocation = cryptographic erasure.
- Forgejo client error messages are **static** (never echoing URL/header/body); `follow_redirects=False` prevents replaying the Authorization header to another host.
- No SECRET_KEY with a weak default (no signing secret at all: everything is hashed randomness).
- Production guarded: allowlist mandatory, OAuth HTTPS mandatory, Secure cookies, Swagger disabled, no `*` CORS.
- Docker: secrets **exclusively via read-only mounted files**, Postgres published on `127.0.0.1` only, privileges dropped.
- Logs: a two-layer key+value net (`logging.py:59-77`) — patterns `fmcp_…`, `Bearer/token …`, `://user:pass@`; an accidental dump of httpx headers would be redacted. On the MCP side, `_safe_error_message` reduces every error to 4 generic messages.

### Findings

| Severity | Finding | Location |
|---|---|---|
| 🟠 MEDIUM | **Credential in `clone_addr` persisted in cleartext in the audit BEFORE rejection.** `record_decision()` (INSERT + commit of `redact_arguments(arguments)`) runs before the `_clone_address()` validation that rejects `https://user:PAT@host/…`; `redact_arguments` has no `://[^@]+@` value pattern (unlike the log formatter). The call fails with a 422, but the upstream token is written into `tool_invocations.redacted_arguments` and served back by the audit API. The existing test covers only a URL **without** credentials — a green witness on the wrong class. | `mcp/server.py:182-196`, `tool_invocation_service.py:121-128`, `client.py:2115-2118` |
| 🟠 MEDIUM | **Committed file contents archived in the audit** (up to 4 KB per field for `changes[].content`). A `.env` or a private key committed via `forgejo_commit_changes` ends up in the audit DB. By contrast, *results* are reduced to size + SHA-256 — the arguments/results asymmetry is the hole. | `audit/redaction.py:51-53` |
| 🟠 MEDIUM | `verify_tls: false` freely configurable by the admin, with no deployment flag (cleartext HTTP requires one) → MITM captures the PAT and the traffic | `api/forgejo_instance.py:16` |
| 🟠 MEDIUM | Images pinned by mutable tag (`python:3.12-slim`, `postgres:16-alpine`…), not by `@sha256:` digest | `deploy/Dockerfile`, `compose.yaml:70,88,107` |
| 🟡 LOW | Single-version key rotation: incrementing the version makes everything undecryptable (an operational trap, honestly documented) | `cipher.py:66-67` |
| 🟡 LOW | Redaction by key only: `api_key`, `passwd`, `private_key` pass through (a dormant risk held in check by the current content of the schemas, not by the code) | `audit/redaction.py:6-13` |
| 🟡 LOW | The application port is published on all interfaces (`0.0.0.0`) whereas Postgres is correctly bounded; default `database_url` containing `change-me`; default bootstrap username `admin` | `compose.yaml:52`, `config.py:21` |

### Doctrine (`docs/security/credentials.md`) vs code

| Promise | Verdict |
|---|---|
| AES-256-GCM, key from a file, fresh nonce, AAD | ✅ compliant |
| The admin can neither submit nor read the PAT | ✅ |
| Revocation = cryptographic erasure | ✅ |
| "PATs never in logs, audit, API responses, exceptions" | ⚠️ **total rule, partial implementation**: true for the PAT of the intended flow, false for *upstream* secrets passed as tool arguments (findings above) |

---

## 5. 🛠️ Tool layer / Forgejo client

### Strong points verified

- **The "selector verified but not the execution" pitfall is avoided**: the authorization decision is **recomputed at every `tools/call`** (`mcp/server.py:176-193`), before any service is constructed; 6 fail-closed layers (`authorization/tools.py:20-32`): valid token ∧ active user ∧ tool globally enabled (**default = disabled**) ∧ user allowance ∧ token grant ∧ active credential. Unknown tool → deny. Unit and integration tests cover each layer.
- **No confused deputy**: exclusively the calling user's PAT, bound by AAD, checked against their Forgejo identity declared at registration; no tool argument can designate a credential/user/base URL.
- **Audit receipt written and COMMITTED before the Forgejo call** (status `PENDING` → `SUCCESS`/`FAILURE`); failure to write the receipt = no execution (**fail-closed**); refused invocations are recorded (`DENIED` + reason); **read-only audit API** (no modification/deletion endpoint); denormalized fields robust to renames.
- Instance SSRF: admin-only URL, http/https schemes only (no `file://`), no credentials/query/fragment, allowlist **reapplied on every PAT-bearing call**, redirects = error.
- Inputs doubly bounded (JSON schema + client revalidation): pagination, sizes, lists, closed enums, `additionalProperties: false` everywhere, RFC 3339 timestamps; responses bounded to 10 MB, streamed and re-validated by Pydantic with `strict=True`.
- `/mcp`: Streamable HTTP only, auth stack before the endpoint, rate limit per token AND per user, allowlisted Origin, CORS without credentials, body capped at 2 MB, coordinated drain at shutdown.

### Findings

| Severity | Finding | Location |
|---|---|---|
| 🔴 HIGH | Dot-segment traversal (detail in §2, HIGH #1) | `client.py:2232-2266` |
| 🟠 MEDIUM | Reference containers on `0.0.0.0:8000` **without enforced TLS**; the MCP bearer and the cookies travel in cleartext if exposed without a reverse proxy (documented, not enforced by the code) | `Dockerfile:31`, `compose.yaml:50` |
| 🟠 MEDIUM | `clone_addr`: private-host guard **without DNS resolution** — a public name resolving to `169.254.169.254` gets through; rebinding not covered. Nuance: the request is executed by Forgejo, and the guard is defense in depth in front of Forgejo's own allowlists | `client.py:2104-2141` |
| 🟡 LOW | `normalize_base_url` does not exclude private hosts (admin-only, allowlist in production; dev/test = anything permitted) | `client.py:104-126` |
| 🟡 LOW | Actions log zip decompression: up to ~100×10 MB of CPU churn from a hostile Forgejo | `client.py:1380-1402` |
| 🟡 LOW | The `forgejo_http_status` column is exposed by the audit API but **never populated** (a surface that advertises data no path produces); audit `target` = the supplied arguments, not the effective URL; a crash after the call leaves an ambiguous but visible `PENDING` | `db/models.py:354` |
| ℹ️ Note | Text contents are passed through to Forgejo as-is (Markdown, workflows via `commit_changes`) — expected client behavior, and Forgejo's responsibility | `client.py:943-992` |

---

## 6. 📋 Cross-check against the repository self-audit (`security-audit-2026-08-31.md`)

| Self-audit claim | Verdict of this audit |
|---|---|
| SEC-001 (URL pinning) "fixed" | ✅ in production; ⚠️ **reopened outside production** (empty allowlist = everything permitted) — HIGH #2 |
| SEC-002 (migration SSRF) "fixed" | ✅ guard present; ⚠️ without DNS resolution (rebinding, public name → internal IP) |
| SEC-003 (`/mcp` Origin) "fixed" | ✅ verified |
| SEC-004 (bounded responses) "fixed" | ✅ verified (stream + 10 MB cap) |
| SEC-005 (invitation race) "fixed" | ✅ verified (`FOR UPDATE`) |
| SEC-006 (log redaction) "fixed" | ✅ on the log side; ⚠️ the invocation audit remains permeable (credential-bearing URL, committed contents) |
| "Path traversal: no exploitable traversal found; repository paths reject `..`" | ❌ **REFUTED** — true for file paths only; owner/repo/refs accept `..` (HIGH #1) |
| "Permission bypass: no bypass found, fail-closed" | ✅ for the grant model itself; ⚠️ its granularity is bypassable via HIGH #1 |
| "Secret storage: no defect" | ✅ verified |

---

## 7. ✅ Prioritized recommendations

1. **[HIGH #1]** Reject `{".", ".."}` in `_repository_name` and `_ref_value` + fix the schema patterns (`registry.py:89-90`). A few lines, with a witness test on `owner=".."` (a positive control that fails before and passes after).
2. **[HIGH #2]** Make `permits_forgejo_base_url` refuse an empty list outside production too, or at the very least emit a loud warning at startup.
3. **[MED. 4-5]** Add a `://[^@]+@` value pattern to `redact_arguments` (aligned with `logging.py:21`) and/or validate `clone_addr` **before** `record_decision`; reduce `changes[].content` to size + SHA-256 in the audit (as `summarize_result` already does).
4. **[MED. 3]** Handle trusted proxies explicitly (`Forwarded`/allowlist) for rate limiting, or document direct exposure as a hard constraint.
5. **[MED. 6-7]** Gate `verify_tls=false` behind a deployment flag as cleartext HTTP is; pin images by `@sha256:` digest; enforce/document TLS termination in front of `0.0.0.0:8000`.
6. **[LOW]** Configurable max TTL for static MCP tokens; purge of the in-memory limiters; revocation of issued tokens on OAuth code replay; populate or remove `forgejo_http_status`; extend the redaction fragments (`api_key`, `private_key`).

---

## Appendix — method

- 4 parallel read-only passes: malware/supply-chain (raw greps, lockfiles, CI, git), auth/OAuth 2.1, crypto/credentials, tool layer/client.
- httpx behavior (dot-segment normalization) **verified by execution** in the project venv, not asserted from memory.
- Documented doctrine systematically confronted with the real code (a docstring can state a total rule that the code implements only in part).
- No source file modified; this report is the only file added.
