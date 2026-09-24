"""The publication gate is only worth running if it still fires on its own witnesses."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "scrub-check.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _load_gate():
    """Import the gate as a module.

    It is a script, not a package member, and `dataclass` resolves its string
    annotations through `sys.modules`, so the entry must exist before exec.
    """
    from importlib import util

    spec = util.spec_from_file_location("scrub_check", GATE)
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    sys.modules["scrub_check"] = module
    spec.loader.exec_module(module)
    return module


def test_every_rule_fires_on_its_positive_witness() -> None:
    result = _run("--self-test")
    assert result.returncode == 0, result.stderr
    assert "fired on their positive witnesses" in result.stdout


def test_a_secret_in_the_range_is_refused(tmp_path: Path) -> None:
    """A green gate means nothing unless a planted secret turns it red.

    The witness is assembled from fragments so that no secret-shaped literal is
    written into this file for the gate to find when it scans itself.
    """
    password = "".join(["Qk4", "mR8vT2wLx", "7Zn5Bd"])
    host = "".join(["192.", "168.", "0.", "213"])
    planted = tmp_path / "planted.md"
    planted.write_text(f"admin_password = {password}\nbackend at {host}:8020\n")

    module = _load_gate()

    hits = [
        rule_id
        for line in planted.read_text().splitlines()
        for rule_id, _length in module.scan_line(line, module.CONTENT_RULES)
    ]
    assert "assigned_secret" in hits
    assert "private_ipv4" in hits


def test_a_finding_never_prints_the_value() -> None:
    """A gate that echoes the secret into the push log publishes what it guards."""
    module = _load_gate()

    password = "".join(["Qk4", "mR8vT2wLx", "7Zn5Bd"])
    rendered = module.Finding("assigned_secret", "deploy/notes.md", 7, len(password)).render()
    assert password not in rendered
    assert "deploy/notes.md:7" in rendered
    assert str(len(password)) in rendered
