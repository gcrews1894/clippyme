"""Tests for clippyme.domain.url_utils.

Pinned down because these helpers protect every disk-side consumer
(publish, compose, smartcut, subtitle, reframe, restore) from returning
'clip file not found' errors when video_url contains a cache-busting
query string or fragment.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from clippyme.domain.url_utils import filename_from_video_url  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Happy path
        ("/videos/abc123/clip_1.mp4", "clip_1.mp4"),
        # Cache-busting query string (the original bug)
        ("/videos/abc123/clip_1.mp4?v=1712584800", "clip_1.mp4"),
        # Multiple query params
        ("/videos/abc/clip_2.mp4?v=123&foo=bar", "clip_2.mp4"),
        # Fragment
        ("/videos/abc/clip_3.mp4#t=30", "clip_3.mp4"),
        # Fragment + query
        ("/videos/abc/clip_4.mp4?v=1#t=30", "clip_4.mp4"),
        # Leading/trailing whitespace
        ("  /videos/abc/clip_5.mp4  ", "clip_5.mp4"),
        # Trailing slash
        ("/videos/abc/clip_6.mp4/", "clip_6.mp4"),
        # Windows-style backslash (defensive)
        ("\\videos\\abc\\clip_7.mp4", "clip_7.mp4"),
        # Just a bare filename
        ("clip_8.mp4", "clip_8.mp4"),
        # Bare filename with query
        ("clip_9.mp4?v=1", "clip_9.mp4"),
        # Empty / None / non-string
        ("", ""),
        (None, ""),
        (123, ""),
        (["clip_1.mp4"], ""),
        # Whitespace only
        ("   ", ""),
        # Just a slash
        ("/", ""),
    ],
)
def test_filename_from_video_url(raw, expected):
    assert filename_from_video_url(raw) == expected


def test_filename_from_video_url_preserves_dots_in_filename():
    assert filename_from_video_url("/videos/x/my.video.clip.mp4") == "my.video.clip.mp4"


def test_filename_from_video_url_http_absolute():
    """Absolute http URLs are rare in practice but should still work."""
    assert (
        filename_from_video_url("http://localhost:8000/videos/abc/clip_1.mp4?v=5")
        == "clip_1.mp4"
    )
