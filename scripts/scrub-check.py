#!/usr/bin/env python3
"""Refuse to publish commits that carry deployment secrets or private infrastructure.

This repository is developed against a private Forgejo instance and published to a
public remote. The two remotes do not deserve the same trust: a deployment secret or
an internal host name that is harmless on the private forge becomes permanent once it
reaches the public one. This gate reads the commits that are about to cross that line
and refuses the push when it finds material that belongs only on the private side.

Two properties make the verdict worth believing:

  - The instrument is validated on positive witnesses before every scan. Each rule is
    run against a sample it is supposed to catch, and against a sample it must ignore.
    A rule that stays silent on its own witness aborts the run, so a reported "no
    finding" is never the silence of a broken pattern.
  - A finding never prints what it found. The report carries the rule, the path, the
    line number and the length of the match. Printing the match would publish, in the
    push log, exactly the value the gate exists to keep unpublished.

The witnesses are assembled from fragments at run time so that no secret-shaped
literal exists in this file for the gate to trip over when scanning itself.

Usage:
    scripts/scrub-check.py --range <already-published>..<new>
    scripts/scrub-check.py --self-test
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "publication-allowlist.txt"
PUBLIC_REMOTE = "origin"


def _joined(*parts: str) -> str:
    """Build a witness from fragments, so this file holds no secret-shaped literal."""
    return "".join(parts)


@dataclass(frozen=True)
class ContentRule:
    rule_id: str
    description: str
    pattern: re.Pattern[str]
    catches: tuple[str, ...]
    ignores: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathRule:
    rule_id: str
    description: str
    globs: tuple[str, ...]
    catches: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    exempt_globs: tuple[str, ...] = ("*example*", "*sample*")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str
    line: int
    match_length: int

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        if self.match_length:
            return f"  {self.rule_id:<22} {where}  ({self.match_length} characters, not shown)"
        return f"  {self.rule_id:<22} {where}"


# A placeholder is a value a reader is expected to replace. Treating one as a secret
# trains the reader to wave the gate through, which costs more than the finding saves.
_PLACEHOLDER = re.compile(
    r"^(?:\$\{|\$[A-Z]|<|\{\{|%\()"
    r"|^(?i:change[_-]?me|example|placeholder|redacted|your[_-]|xxx|\.\.\.|none|null|true|false)",
)

CONTENT_RULES: tuple[ContentRule, ...] = (
    ContentRule(
        rule_id="pem_private_key",
        description="an inlined private key block",
        pattern=re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
        catches=(_joined("-----BEGIN ", "RSA PRIVATE", " KEY-----"),),
        ignores=("-----BEGIN CERTIFICATE-----", "-----BEGIN PUBLIC KEY-----"),
    ),
    ContentRule(
        rule_id="url_credentials",
        description="a URL carrying an inline password",
        pattern=re.compile(
            r"\b[a-z][a-z0-9+.\-]*://[^\s:/@'\"]+:(?P<value>[^\s@/'\"]{4,})@",
        ),
        catches=(_joined("postgresql+asyncpg://app", ":", "9f3aa17c4b", "@", "db:5432/x"),),
        ignores=(
            "postgresql+asyncpg://forgejo_mcp:${POSTGRES_PASSWORD}@postgres:5432/forgejo_mcp",
            "https://git.example.com/api/v1",
            "git@github.com:owner/repo.git",
        ),
    ),
    ContentRule(
        rule_id="assigned_secret",
        description="a secret-shaped value assigned to a secret-shaped name",
        pattern=re.compile(
            r"(?i)(?<![A-Za-z0-9])(?:pass(?:word|wd)?|secret|token|api[_-]?key|credential"
            r"|private[_-]?key|access[_-]?key)(?![A-Za-z0-9])[\"']?\s*[:=]\s*[\"']?"
            r"(?P<value>[A-Za-z0-9+/_=\-]{16,})",
        ),
        catches=(_joined("admin_password", " = ", "Tq8", "vN2mR7wLx4Zk", "0Ab"),),
        ignores=(
            "FMCP_CREDENTIAL_KEY=${CREDENTIAL_KEY}",
            'token = "<your-mcp-token>"',
            "password: changeme-before-first-boot",
            "api_key = os.environ['FMCP_API_KEY']",
        ),
    ),
    ContentRule(
        rule_id="mcp_token",
        description="an issued MCP bearer token",
        pattern=re.compile(r"\bfmcp_[A-Za-z0-9_\-]{16,}"),
        catches=(_joined("fmcp", "_", "7Kd2pQ", "mXr9Lt4vB", "wN6s"),),
        ignores=("Authorization: Bearer fmcp_...", "prefix is `fmcp_`"),
    ),
    ContentRule(
        rule_id="bearer_literal",
        description="a literal bearer credential",
        pattern=re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"),
        catches=(_joined("Authorization: Bearer ", "eyJhbGciOi", "JIUzI1NiJ9.", "abcdef1234"),),
        ignores=("Authorization: Bearer <token>", "Authorization: Bearer fmcp_..."),
    ),
    ContentRule(
        rule_id="base64_key_material",
        description="a base64-encoded 32-byte key, the shape this deployment generates",
        pattern=re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/=])"),
        catches=(_joined("K9x", "2Lm4Pq7Rt1Vw", "8Yz3Bd6Gh0Jk", "5Nn2Ss9Uu4Xx", "7Cc1="),),
        ignores=("openssl rand -base64 32 > deploy/secrets/credential_key",),
    ),
    ContentRule(
        rule_id="private_ipv4",
        description="an RFC 1918 address, which names a host on the author's network",
        pattern=re.compile(
            r"\b(?:10\.[0-9]{1,3}|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))"
            r"\.[0-9]{1,3}\.[0-9]{1,3}\b",
        ),
        catches=(_joined("connects to ", "192.", "168.", "0.", "15", ":3040"),),
        ignores=("http://127.0.0.1:8000/health/ready", "bind 0.0.0.0", "version 10.2.1"),
    ),
)


PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        rule_id="secret_file",
        description="a file whose whole purpose is to hold a secret",
        globs=(
            ".env",
            "*/.env",
            ".env.*",
            "*/.env.*",
            "secrets/*",
            "*/secrets/*",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
        ),
        catches=("deploy/.env", "deploy/secrets/credential_key", "certs/server.key"),
        ignores=(
            "deploy/compose.example.env",
            ".env.example",
            "src/forgejo_mcp/keys.py",
            "docs/security/credentials.md",
        ),
    ),
    PathRule(
        rule_id="local_state_file",
        description="local runtime state that records what this machine did",
        globs=("*.sqlite", "*.sqlite3", "*.log", "*.pid"),
        catches=("deploy/app.sqlite3", "scratch/e2e.log"),
        ignores=("docs/logging.md", "src/forgejo_mcp/logging.py"),
    ),
)


@dataclass
class Allowlist:
    entries: list[tuple[str, str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Allowlist:
        entries: list[tuple[str, str, str]] = []
        if not path.exists():
            return cls(entries)
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 3:
                raise SystemExit(f"{path}: malformed entry, expected 'rule | path | reason': {raw}")
            entries.append((parts[0], parts[1], parts[2]))
        return cls(entries)

    def permits(self, rule_id: str, path: str) -> bool:
        return any(
            rule == rule_id and fnmatch.fnmatch(path, glob) for rule, glob, _ in self.entries
        )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def private_remote_hosts() -> tuple[str, ...]:
    """Host names of every remote that is not the public one.

    Read at run time rather than hardcoded: the private infrastructure of a checkout is
    whatever it pushes to besides the public remote, and naming it in this file would
    itself publish it.
    """
    remotes: dict[str, str] = {}
    for line in _git("remote", "-v").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            host = urlparse(parts[1]).hostname
            if host:
                remotes[parts[0]] = host

    # A remote that shares the public remote's host is public too, whatever it is
    # called. `upstream` on the same forge as `origin` is the common case, and
    # watching its host would flag every ordinary mention of the public forge.
    public_host = remotes.get(PUBLIC_REMOTE)
    hosts = {
        host
        for name, host in remotes.items()
        if name != PUBLIC_REMOTE and host != public_host and host not in {"localhost", "127.0.0.1"}
    }
    return tuple(sorted(hosts))


def private_host_rule(hosts: tuple[str, ...]) -> ContentRule | None:
    if not hosts:
        return None
    return ContentRule(
        rule_id="private_remote_host",
        description="the host name of a remote that is not the public one",
        pattern=re.compile("|".join(re.escape(host) for host in hosts), re.IGNORECASE),
        catches=(f"git remote add forge https://{hosts[0]}/owner/repo.git",),
        ignores=("https://git.example.com/owner/repo.git",),
    )


def scan_line(line: str, rules: tuple[ContentRule, ...]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for rule in rules:
        for match in rule.pattern.finditer(line):
            value = match.groupdict().get("value") or match.group(0)
            if _PLACEHOLDER.search(value):
                continue
            hits.append((rule.rule_id, len(value)))
    return hits


def path_hits(path: str) -> list[str]:
    hits: list[str] = []
    for rule in PATH_RULES:
        if any(fnmatch.fnmatch(path, glob) for glob in rule.exempt_globs):
            continue
        if any(fnmatch.fnmatch(path, glob) for glob in rule.globs):
            hits.append(rule.rule_id)
    return hits


def self_test(rules: tuple[ContentRule, ...]) -> list[str]:
    """Run every rule against what it must catch and what it must ignore.

    A gate is only as trustworthy as the last time it was seen to fire.
    """
    failures: list[str] = []
    for rule in rules:
        for witness in rule.catches:
            if not scan_line(witness, (rule,)):
                failures.append(f"{rule.rule_id}: stayed silent on its positive witness")
        for witness in rule.ignores:
            if scan_line(witness, (rule,)):
                failures.append(f"{rule.rule_id}: fired on a witness it must ignore: {witness}")
    for path_rule in PATH_RULES:
        for witness in path_rule.catches:
            if path_rule.rule_id not in path_hits(witness):
                failures.append(f"{path_rule.rule_id}: missed the path {witness}")
        for witness in path_rule.ignores:
            if path_rule.rule_id in path_hits(witness):
                failures.append(f"{path_rule.rule_id}: fired on the benign path {witness}")
    return failures


def scan_range(
    commit_range: str,
    rules: tuple[ContentRule, ...],
    allowlist: Allowlist,
) -> list[Finding]:
    findings: list[Finding] = []

    for path in _git("diff", "--name-only", "--diff-filter=ACMR", commit_range).splitlines():
        path = path.strip()
        if not path:
            continue
        for rule_id in path_hits(path):
            if not allowlist.permits(rule_id, path):
                findings.append(Finding(rule_id, path, 0, 0))

    current_path = ""
    line_number = 0
    for raw in _git("diff", "--unified=0", commit_range).splitlines():
        if raw.startswith("+++ b/"):
            current_path = raw[6:]
            continue
        if raw.startswith("@@"):
            header = re.search(r"\+(\d+)", raw)
            line_number = int(header.group(1)) if header else 0
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        content = raw[1:]
        for rule_id, length in scan_line(content, rules):
            if not allowlist.permits(rule_id, current_path):
                findings.append(Finding(rule_id, current_path, line_number, length))
        line_number += 1

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", dest="commit_range", help="git range, e.g. origin/main..HEAD")
    parser.add_argument("--self-test", action="store_true", help="validate the rules and exit")
    args = parser.parse_args()

    hosts = private_remote_hosts()
    host_rule = private_host_rule(hosts)
    rules = CONTENT_RULES + ((host_rule,) if host_rule else ())

    failures = self_test(rules)
    if failures:
        print("SCRUB GATE BROKEN - the instrument failed its own witnesses:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print("\nNo verdict is possible until every rule fires on its witness.", file=sys.stderr)
        return 2

    rule_count = len(rules) + len(PATH_RULES)
    if args.self_test:
        print(f"scrub gate validated: {rule_count} rules fired on their positive witnesses")
        print(f"private hosts watched: {len(hosts)} (not named here)")
        return 0

    if not args.commit_range:
        parser.error("--range is required unless --self-test is given")

    allowlist = Allowlist.load(ALLOWLIST_PATH)
    findings = scan_range(args.commit_range, rules, allowlist)

    print(f"scrub gate validated: {rule_count} rules fired on their positive witnesses")
    print(f"scanned: {args.commit_range}")
    if not findings:
        print("PASS no publication finding")
        return 0

    print(f"\nFAIL {len(findings)} publication finding(s); values withheld:", file=sys.stderr)
    for finding in findings:
        print(finding.render(), file=sys.stderr)
    print(
        "\nResolve each one at the source, or record a reviewed exemption in "
        f"{ALLOWLIST_PATH.relative_to(REPO_ROOT)}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
