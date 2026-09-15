import random

import pytest

from forgejo_mcp.forgejo.log_filter import FilteredLog, filter_ci_log

_ISO = "2026-08-18T10:00:01.123456789Z "


def _zero_stats(result: FilteredLog) -> bool:
    return (
        result.removed_ansi,
        result.removed_carriage_returns,
        result.removed_timestamps,
        result.collapsed_lines,
        result.removed_blank_lines,
    ) == (0, 0, 0, 0, 0)


def test_clean_log_is_returned_byte_for_byte_with_zero_counters() -> None:
    log = "step one\nstep two\n\nstep three\n"

    result = filter_ci_log(log)

    assert result.text == log
    assert _zero_stats(result)
    assert result.original_lines == result.filtered_lines == 4


def test_empty_log_stays_empty() -> None:
    result = filter_ci_log("")

    assert result.text == ""
    assert _zero_stats(result)
    assert result.original_lines == result.filtered_lines == 0


def test_log_without_trailing_newline_keeps_its_shape() -> None:
    result = filter_ci_log("alpha\nbeta")

    assert result.text == "alpha\nbeta"
    assert result.original_lines == result.filtered_lines == 2


def test_ansi_csi_and_osc_sequences_are_removed_and_counted() -> None:
    log = (
        "\x1b[32mPASS\x1b[0m tests\n"
        "\x1b[2K\x1b[1Gcursor line\n"
        "\x1b]0;window title\x07plain\n"
        "\x1b]8;;https://example.test\x1b\\link\x1b]8;;\x1b\\\n"
    )

    result = filter_ci_log(log)

    assert result.text == "PASS tests\ncursor line\nplain\nlink\n"
    assert result.removed_ansi == 7
    assert result.removed_timestamps == 0
    assert result.collapsed_lines == 0


def test_carriage_return_keeps_only_the_last_segment_of_a_line() -> None:
    log = "Downloading 10%\rDownloading 55%\rDownloading 100%\nnext\r\n"

    result = filter_ci_log(log)

    assert result.text == "Downloading 100%\nnext\n"
    assert result.removed_carriage_returns == 3
    assert result.removed_ansi == 0
    assert result.original_lines == result.filtered_lines == 2


def test_progress_bar_with_ansi_clears_collapses_to_its_final_state() -> None:
    log = "\x1b[Kstep 1/3\r\x1b[Kstep 2/3\r\x1b[Kstep 3/3\n"

    result = filter_ci_log(log)

    assert result.text == "step 3/3\n"
    assert result.removed_ansi == 3
    assert result.removed_carriage_returns == 2


@pytest.mark.parametrize(
    "prefix",
    [
        "2026-08-18T10:00:01Z ",
        "2026-08-18T10:00:01.5Z ",
        "2026-08-18T10:00:01.123456789Z ",
        "2026-08-18T10:00:01+02:00 ",
        "2026-08-18T10:00:01.000-05:30 ",
        "[10:00:01] ",
        "10:00:01.123 ",
    ],
)
def test_leading_timestamps_are_removed_and_counted(prefix: str) -> None:
    result = filter_ci_log(f"{prefix}build started\n{prefix}build done\n")

    assert result.text == "build started\nbuild done\n"
    assert result.removed_timestamps == 2
    assert result.collapsed_lines == 0


def test_timestamp_alone_on_a_line_leaves_an_empty_line() -> None:
    result = filter_ci_log("[10:00:01]\nnext\n")

    assert result.text == "\nnext\n"
    assert result.removed_timestamps == 1


@pytest.mark.parametrize(
    "line",
    [
        "started at 12:30 by cron",
        "retry 12:30:45 scheduled",
        "at 2026-08-18T10:00:01Z the build finished",
        "12:30:45 no milliseconds so not a known format",
        "2026-08-18 10:00:01 space instead of T",
        "2026-08-18T10:00:01Znospace",
        "10:00:01.12 two-digit fraction",
        " [10:00:01] leading space",
        "  2026-08-18T10:00:01Z indented",
    ],
)
def test_time_like_text_that_is_not_a_leading_timestamp_is_untouched(line: str) -> None:
    result = filter_ci_log(f"{line}\n")

    assert result.text == f"{line}\n"
    assert _zero_stats(result)


def test_lines_differing_only_by_timestamp_are_collapsed() -> None:
    log = (
        f"{_ISO}retrying connection\n"
        "2026-08-18T10:00:02.000000000Z retrying connection\n"
        "2026-08-18T10:00:03.000000000Z retrying connection\n"
        f"{_ISO}connected\n"
    )

    result = filter_ci_log(log)

    assert result.text == "retrying connection [×3]\nconnected\n"
    assert result.removed_timestamps == 4
    assert result.collapsed_lines == 2
    assert result.original_lines == 4
    assert result.filtered_lines == 2


def test_lines_differing_only_by_ansi_colour_are_collapsed() -> None:
    log = "\x1b[33mwarn\x1b[0m\n\x1b[31mwarn\x1b[0m\nwarn\n"

    result = filter_ci_log(log)

    assert result.text == "warn [×3]\n"
    assert result.removed_ansi == 4
    assert result.collapsed_lines == 2


def test_only_consecutive_identical_lines_are_collapsed() -> None:
    log = "a\na\nb\na\na\na\nb\n"

    result = filter_ci_log(log)

    assert result.text == "a [×2]\nb\na [×3]\nb\n"
    assert result.collapsed_lines == 3
    assert result.original_lines == 7
    assert result.filtered_lines == 4


def test_nearly_identical_lines_are_not_collapsed() -> None:
    log = "a\na \nA\na\n"

    result = filter_ci_log(log)

    assert result.text == log
    assert _zero_stats(result)


def test_consecutive_blank_lines_are_reduced_to_one_and_declared() -> None:
    log = "a\n\n\n\nb\n\n"

    result = filter_ci_log(log)

    assert result.text == "a\n\nb\n\n"
    assert result.removed_blank_lines == 2
    assert result.collapsed_lines == 0
    assert result.original_lines == 6
    assert result.filtered_lines == 4


def test_whitespace_only_lines_are_not_blank_lines() -> None:
    log = "a\n \n \nb\n"

    result = filter_ci_log(log)

    assert result.text == "a\n  [×2]\nb\n"
    assert result.removed_blank_lines == 0
    assert result.collapsed_lines == 1


def test_lines_emptied_by_the_filter_join_the_blank_line_rule() -> None:
    log = "a\n\x1b[0m\n\n[10:00:01]\nb\n"

    result = filter_ci_log(log)

    assert result.text == "a\n\nb\n"
    assert result.removed_ansi == 1
    assert result.removed_timestamps == 1
    assert result.removed_blank_lines == 2


def test_all_transformations_combined() -> None:
    log = (
        f"{_ISO}\x1b[1mSetup\x1b[0m\n"
        f"{_ISO}pulling 10%\r{_ISO}pulling 60%\r{_ISO}pulling 100%\n"
        f"{_ISO}\x1b[33mretry\x1b[0m\n"
        f"{_ISO}\x1b[33mretry\x1b[0m\n"
        "\n"
        "\n"
        f"{_ISO}done\n"
    )

    result = filter_ci_log(log)

    assert result.text == "Setup\npulling 100%\nretry [×2]\n\ndone\n"
    assert result.removed_ansi == 6
    assert result.removed_carriage_returns == 2
    assert result.removed_timestamps == 5
    assert result.collapsed_lines == 1
    assert result.removed_blank_lines == 1
    assert result.original_lines == 7
    assert result.filtered_lines == 5


def _realistic_log(target_bytes: int, *, repeated_share: float, seed: int = 7) -> str:
    generator = random.Random(seed)
    palette = ["\x1b[32m", "\x1b[33m", "\x1b[36m", "\x1b[1m"]
    messages = [
        "Run actions/checkout@v4",
        "Fetching the repository",
        "Resolving dependencies for workspace",
        "Compiling module forgejo_mcp.forgejo.client",
        "tests/unit/test_forgejo_action_tools.py::test_job_log PASSED",
        "warning: unused variable `window` in client.py:1347",
        "Waiting for the database container to become healthy",
        "Uploading coverage artifact (chunk)",
    ]
    lines: list[str] = []
    second = 0
    while sum(len(line) for line in lines) < target_bytes:
        second += 1
        minute, seconds, millis = second // 60 % 60, second % 60, second % 1000
        stamp = f"2026-08-18T10:{minute:02d}:{seconds:02d}.{millis:03d}000000Z "
        if lines and generator.random() < repeated_share:
            body = lines[-1].split(" ", 1)[1]
        else:
            colour = generator.choice(palette)
            body = f"{colour}{generator.choice(messages)}\x1b[0m\n"
        lines.append(stamp + body)
    return "".join(lines)


def test_realistic_sixty_four_kib_log_shrinks_by_at_least_thirty_percent() -> None:
    log = _realistic_log(64 * 1024, repeated_share=0.3)
    raw_size = len(log.encode("utf-8"))
    assert raw_size >= 64 * 1024

    result = filter_ci_log(log)

    filtered_size = len(result.text.encode("utf-8"))
    assert filtered_size <= raw_size * 0.7, (raw_size, filtered_size)
    assert result.removed_timestamps == result.original_lines
    assert result.collapsed_lines > 0
    assert result.filtered_lines + result.collapsed_lines == result.original_lines


def test_filtering_is_idempotent_on_its_own_output() -> None:
    log = f"{_ISO}\x1b[1mSetup\x1b[0m\n{_ISO}a\n{_ISO}a\n\n\n{_ISO}b\n"
    first = filter_ci_log(log)

    second = filter_ci_log(first.text)

    assert second.text == first.text
    assert _zero_stats(second)
