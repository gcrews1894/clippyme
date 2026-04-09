"""Regression tests for bugs identified in main.py review.

Each test is tagged with the bug number from the plan so failures are
traceable. Run inside the Docker backend image (host typically lacks
the cv2/mediapipe/yt-dlp runtime deps).
"""
import os
import pytest

from clippyme.pipeline.main import _resolve_cookies_path


def test_bug1_cookie_path_points_at_repo_root_data_dir(tmp_path, monkeypatch):
    repo_root = tmp_path
    data_dir = repo_root / "data"
    data_dir.mkdir()
    (data_dir / "cookies.txt").write_text("# netscape cookies")
    monkeypatch.chdir(repo_root)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    resolved = _resolve_cookies_path(explicit=None)
    assert resolved == str(data_dir / "cookies.txt")


def test_bug1_cookie_explicit_override_wins(tmp_path):
    explicit = tmp_path / "my_cookies.txt"
    explicit.write_text("x")
    assert _resolve_cookies_path(explicit=str(explicit)) == str(explicit)


def test_bug1_cookie_env_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOUTUBE_COOKIES", "# cookies from env")
    resolved = _resolve_cookies_path(explicit=None)
    assert resolved is not None
    assert os.path.exists(resolved)


def test_bug1_cookie_none_when_nothing_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    assert _resolve_cookies_path(explicit=None) is None
