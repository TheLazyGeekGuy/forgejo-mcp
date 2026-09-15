"""Opt-in noise filter for CI logs.

The filter works by subtraction and only knows a closed set of noise shapes: ANSI escape
sequences, carriage-return rewrites (progress bars), a few leading timestamp formats, runs
of identical lines and runs of blank lines. Anything it does not recognise passes through
untouched. Because a subtractive filter is transparent to formats it does not know, the
result declares exactly what was removed and claims nothing more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import groupby

# CSI: ESC [ parameter bytes (0x30-0x3F), intermediate bytes (0x20-0x2F), final byte (0x40-0x7E).
# Covers SGR colours (`m`), cursor movement (`A`-`H`), erase (`J`, `K`) and friends.
_CSI = r"\x1b\[[0-?]*[ -/]*[@-~]"
# OSC: ESC ] ... terminated by BEL or ST (ESC \).
_OSC = r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
_ANSI = re.compile(f"{_CSI}|{_OSC}")

# Leading timestamps, each a closed shape followed by one space or the end of the line:
#   2026-08-18T10:00:01Z, 2026-08-18T10:00:01.123456789+02:00 (ISO 8601 with offset),
#   [10:00:01],
#   10:00:01.123.
_TIMESTAMP = re.compile(
    r"^(?:"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})"
    r"|\[\d{2}:\d{2}:\d{2}\]"
    r"|\d{2}:\d{2}:\d{2}\.\d{3}"
    r")(?: |$)"
)


@dataclass(frozen=True)
class FilteredLog:
    """A filtered log and an account of everything the filter removed."""

    text: str
    removed_ansi: int
    removed_carriage_returns: int
    removed_timestamps: int
    collapsed_lines: int
    removed_blank_lines: int
    original_lines: int
    filtered_lines: int

    def stats(self) -> dict[str, int]:
        return {
            "removed_ansi": self.removed_ansi,
            "removed_carriage_returns": self.removed_carriage_returns,
            "removed_timestamps": self.removed_timestamps,
            "collapsed_lines": self.collapsed_lines,
            "removed_blank_lines": self.removed_blank_lines,
            "original_lines": self.original_lines,
            "filtered_lines": self.filtered_lines,
        }


def filter_ci_log(text: str) -> FilteredLog:
    """Strip known CI noise from ``text`` and report what was removed.

    Applied in order, line by line: ANSI CSI/OSC sequences are removed; only the text after
    the last carriage return of a line is kept (a trailing ``\\r`` is dropped, so CRLF lines
    keep their content); a leading timestamp in one of the known shapes is removed. Then
    runs of strictly identical lines collapse into one line suffixed with `` [×N]`` and runs
    of blank lines collapse into one blank line. A log without noise is returned unchanged
    with every counter at zero.
    """
    if text == "":
        return FilteredLog(
            text="",
            removed_ansi=0,
            removed_carriage_returns=0,
            removed_timestamps=0,
            collapsed_lines=0,
            removed_blank_lines=0,
            original_lines=0,
            filtered_lines=0,
        )
    terminated = text.endswith("\n")
    lines = text.split("\n")
    if terminated:
        lines.pop()

    removed_ansi = 0
    removed_carriage_returns = 0
    removed_timestamps = 0
    cleaned: list[str] = []
    for line in lines:
        line, ansi_count = _ANSI.subn("", line)
        removed_ansi += ansi_count
        if "\r" in line:
            removed_carriage_returns += line.count("\r")
            line = line.rstrip("\r").rsplit("\r", 1)[-1]
        line, timestamp_count = _TIMESTAMP.subn("", line, count=1)
        removed_timestamps += timestamp_count
        cleaned.append(line)

    collapsed_lines = 0
    removed_blank_lines = 0
    kept: list[str] = []
    for line, run in groupby(cleaned):
        count = sum(1 for _ in run)
        if line == "":
            removed_blank_lines += count - 1
            kept.append(line)
        elif count > 1:
            collapsed_lines += count - 1
            kept.append(f"{line} [×{count}]")
        else:
            kept.append(line)

    filtered = "\n".join(kept) + ("\n" if terminated else "")
    return FilteredLog(
        text=filtered,
        removed_ansi=removed_ansi,
        removed_carriage_returns=removed_carriage_returns,
        removed_timestamps=removed_timestamps,
        collapsed_lines=collapsed_lines,
        removed_blank_lines=removed_blank_lines,
        original_lines=len(lines),
        filtered_lines=len(kept),
    )
