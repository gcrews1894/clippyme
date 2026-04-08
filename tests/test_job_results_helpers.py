"""Focused tests for the pure helpers in clippyme.domain.job_results.

Kept separate from test_backend_fixes.py so we don't need to import
the full FastAPI app (which pulls in dotenv, uvicorn, etc.).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from clippyme.domain.job_results import (  # noqa: E402
    _pick_latest_metadata,
    build_main_cmd,
    load_final_result,
    load_partial_result,
)
from clippyme.domain.history_service import is_valid_job_id  # noqa: E402


# --- is_valid_job_id -------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("12345678-1234-4abc-8def-1234567890ab", True),
        ("12345678-1234-4ABC-8DEF-1234567890AB", True),  # case-insensitive
        ("not-a-uuid", False),
        ("", False),
        (None, False),  # defensive: previously raised TypeError
        (12345, False),
        (b"12345678-1234-4abc-8def-1234567890ab", False),
        ("12345678-1234-1abc-8def-1234567890ab", False),  # not v4
    ],
)
def test_is_valid_job_id(value, expected):
    assert is_valid_job_id(value) is expected


# --- build_main_cmd --------------------------------------------------------


def test_build_main_cmd_url_basic():
    cmd = build_main_cmd(url="https://youtu.be/abc", output_dir="/tmp/out")
    assert cmd[:4] == ["python", "-u", "-m", "clippyme.pipeline.main"]
    assert "-u" in cmd and "https://youtu.be/abc" in cmd
    assert "-o" in cmd and "/tmp/out" in cmd


def test_build_main_cmd_rejects_reframe_mode():
    with pytest.raises(ValueError, match="invalid reframe_mode"):
        build_main_cmd(url="https://x", output_dir="/tmp", reframe_mode="sideways")


def test_build_main_cmd_rejects_long_instructions():
    long_str = "x" * 2001
    with pytest.raises(ValueError, match="instructions too long"):
        build_main_cmd(url="https://x", output_dir="/tmp", instructions=long_str)


def test_build_main_cmd_blocks_argv_injection_url():
    """URL starting with '-' would be parsed as a new flag by argparse."""
    with pytest.raises(ValueError, match="url must not start with"):
        build_main_cmd(url="--evil-flag", output_dir="/tmp")


def test_build_main_cmd_blocks_argv_injection_input_path():
    with pytest.raises(ValueError, match="input_path must not start with"):
        build_main_cmd(input_path="--evil-flag", output_dir="/tmp")


def test_build_main_cmd_includes_reframe_mode_when_disabled():
    cmd = build_main_cmd(
        url="https://x",
        output_dir="/tmp",
        reframe_mode="disabled",
    )
    assert "--reframe-mode" in cmd
    idx = cmd.index("--reframe-mode")
    assert cmd[idx + 1] == "disabled"


def test_build_main_cmd_omits_reframe_mode_when_auto():
    """auto is the default — don't pass the flag."""
    cmd = build_main_cmd(url="https://x", output_dir="/tmp", reframe_mode="auto")
    assert "--reframe-mode" not in cmd


# --- _pick_latest_metadata -------------------------------------------------


def test_pick_latest_metadata_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert _pick_latest_metadata(d) is None


def test_pick_latest_metadata_picks_newest():
    with tempfile.TemporaryDirectory() as d:
        older = os.path.join(d, "A_metadata.json")
        newer = os.path.join(d, "B_metadata.json")
        with open(older, "w") as f:
            f.write("{}")
        time.sleep(0.05)
        with open(newer, "w") as f:
            f.write("{}")
        # Force older mtime clearly in the past
        os.utime(older, (time.time() - 100, time.time() - 100))
        assert _pick_latest_metadata(d) == newer


# --- load_final_result corrupt metadata -----------------------------------


def test_load_final_result_handles_corrupt_json():
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "X_metadata.json")
        with open(bad, "w") as f:
            f.write("{not valid json")
        # Must not raise — corrupt metadata is equivalent to missing.
        result = load_final_result("deadbeef-1234-4abc-8def-1234567890ab", d)
        assert result is None


def test_load_partial_result_handles_missing_dir():
    with tempfile.TemporaryDirectory() as d:
        result = load_partial_result("deadbeef-1234-4abc-8def-1234567890ab", os.path.join(d, "nope"))
        assert result is None


def test_load_final_result_with_valid_metadata():
    with tempfile.TemporaryDirectory() as d:
        meta = os.path.join(d, "myvideo_metadata.json")
        payload = {
            "shorts": [
                {
                    "start": 10.0,
                    "end": 25.0,
                    "viral_score": 90,
                    "viral_reason": "Strong hook with clean payoff in under twenty seconds",
                    "viral_hook_text": "This changes everything",
                    "video_title_for_youtube_short": "Title",
                }
            ],
        }
        with open(meta, "w") as f:
            json.dump(payload, f)
        # Create the clip file so _build_clips includes it
        open(os.path.join(d, "myvideo_clip_1.mp4"), "wb").write(b"fake")
        result = load_final_result("deadbeef-1234-4abc-8def-1234567890ab", d)
        assert result is not None
        assert len(result["clips"]) == 1
        assert result["clips"][0]["video_url"].endswith("myvideo_clip_1.mp4")
        # Hook preserved (no backfill needed)
        assert result["clips"][0]["viral_hook_text"] == "This changes everything"
