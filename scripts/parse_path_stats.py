#!/usr/bin/env python3
"""Report the distribution of Gemini parse paths from backend logs.

Reads any log source passed via argv (stdin by default) and counts
occurrences of the structured log line emitted by main.py:

    📊 gemini_parse path=<strict|clean|json_repair|retry|fallback> ...

Usage:
    # from stdin (e.g. docker compose logs backend | ... )
    docker compose logs backend | python scripts/parse_path_stats.py

    # from specific files
    python scripts/parse_path_stats.py data/logs/backend-*.log

Exit code is non-zero when the proportion of retry + fallback exceeds
RETRY_FALLBACK_ALERT_THRESHOLD — useful as a CI/cron health check.

This script is deliberately dependency-free: pure stdlib, Python 3.9+.
"""
from __future__ import annotations

import fileinput
import re
import sys
from collections import Counter
from typing import Iterable

PATH_PATTERN = re.compile(
    r"gemini_parse\s+path=(?P<path>strict|clean|json_repair|retry|fallback)"
)

KNOWN_PATHS = ("strict", "clean", "json_repair", "retry", "fallback")
RETRY_FALLBACK_ALERT_THRESHOLD = 0.02  # 2% warrants investigation


def count_paths(lines: Iterable[str]) -> Counter:
    counter: Counter = Counter()
    for line in lines:
        match = PATH_PATTERN.search(line)
        if match:
            counter[match.group("path")] += 1
    return counter


def format_report(counter: Counter) -> str:
    total = sum(counter.values())
    if total == 0:
        return "No gemini_parse log lines found."

    lines = [f"Gemini parse-path distribution ({total} events):\n"]
    for path in KNOWN_PATHS:
        n = counter.get(path, 0)
        pct = (n / total * 100) if total else 0.0
        bar = "█" * int(pct / 2)
        lines.append(f"  {path:<12} {n:>6}  {pct:5.1f}%  {bar}")

    retry_fallback = counter.get("retry", 0) + counter.get("fallback", 0)
    rf_pct = retry_fallback / total if total else 0.0
    lines.append("")
    if rf_pct > RETRY_FALLBACK_ALERT_THRESHOLD:
        lines.append(
            f"⚠️  ALERT: retry+fallback at {rf_pct * 100:.2f}% "
            f"(threshold {RETRY_FALLBACK_ALERT_THRESHOLD * 100:.0f}%). "
            "Investigate Gemini prompt drift."
        )
    else:
        lines.append(
            f"✅ retry+fallback at {rf_pct * 100:.2f}% (healthy, "
            f"< {RETRY_FALLBACK_ALERT_THRESHOLD * 100:.0f}% threshold)."
        )
    return "\n".join(lines)


def main() -> int:
    # fileinput handles both stdin and argv file paths. The encoding
    # kwarg only exists on 3.10+, so we fall back to the default on
    # older runtimes (UTF-8 is the platform default on macOS/Linux).
    try:
        stream = fileinput.input(encoding="utf-8", errors="replace")
    except TypeError:
        stream = fileinput.input()
    with stream:
        counter = count_paths(stream)

    print(format_report(counter))

    total = sum(counter.values())
    if total == 0:
        return 0
    retry_fallback = counter.get("retry", 0) + counter.get("fallback", 0)
    if retry_fallback / total > RETRY_FALLBACK_ALERT_THRESHOLD:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
