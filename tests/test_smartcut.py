"""Unit tests for smartcut.py — focus on the pure-python logic that doesn't
need a real video file or auto-editor binary on PATH.

Run with:
    python -m pytest tests/test_smartcut.py -v
"""
import json
import os
import sys
import tempfile

# Allow `from clippyme.domain import smartcut` via the src layout.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from clippyme.domain import smartcut  # noqa: E402


# ---------------------------------------------------------------------------
# Token normalization
# ---------------------------------------------------------------------------

def test_normalize_strips_punctuation():
    assert smartcut._normalize_token("(uh,)") == "uh"
    assert smartcut._normalize_token("Ehm;") == "ehm"
    assert smartcut._normalize_token('"You know"') == "you know"
    assert smartcut._normalize_token("um--") == "um"
    assert smartcut._normalize_token("¿bueno?") == "bueno"
    assert smartcut._normalize_token("…ah…") == "ah"


def test_normalize_handles_unicode_quotes():
    # Typographic quotes should be stripped, not preserved as letters.
    assert smartcut._normalize_token("\u201cwell\u201d") == "well"


# ---------------------------------------------------------------------------
# Filler index construction
# ---------------------------------------------------------------------------

def test_filler_index_includes_multiword_phrases():
    fillers, max_n = smartcut._build_filler_index("en")
    assert "you know" in fillers
    assert "uh huh" in fillers
    assert "i mean" in fillers
    assert max_n == 2  # all multi-word entries are 2-grams


def test_filler_index_unknown_lang_falls_back_to_default():
    fillers, _ = smartcut._build_filler_index("xx")
    en_fillers, _ = smartcut._build_filler_index("en")
    assert fillers == en_fillers


def test_filler_index_normalizes_entries():
    # vabbè (with grave accent) should survive normalization (it's \w-class)
    it_fillers, _ = smartcut._build_filler_index("it")
    assert "vabbè" in it_fillers or "vabbe" in it_fillers


# ---------------------------------------------------------------------------
# analyze_silences — the heart of stage 1
# ---------------------------------------------------------------------------

def _make_transcript(words):
    return {"segments": [{"words": words}]}


def test_multiword_filler_detection():
    """Regression test: 'you know' was dead config in the previous version
    because the loop iterated single tokens. The n-gram lookahead fix means
    both words of a 2-gram filler are removed."""
    transcript = _make_transcript([
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "you", "start": 0.6, "end": 0.8},
        {"word": "know", "start": 0.85, "end": 1.1},
        {"word": "world", "start": 1.2, "end": 1.6},
    ])
    segs, stats = smartcut.analyze_silences(transcript, 0.0, 2.0, "en")
    assert stats["fillers_removed"] == 2  # both 'you' and 'know'


def test_punctuation_wrapped_filler():
    """Single fillers wrapped in punctuation should still match."""
    transcript = _make_transcript([
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "(uh,)", "start": 0.6, "end": 0.8},
        {"word": "world", "start": 1.0, "end": 1.4},
    ])
    _, stats = smartcut.analyze_silences(transcript, 0.0, 2.0, "en")
    assert stats["fillers_removed"] == 1


def test_silence_gap_detection():
    """A 2-second gap between two words should be flagged as silence."""
    transcript = _make_transcript([
        {"word": "Hello", "start": 0.0, "end": 0.5},
        # 2-second silence here
        {"word": "world", "start": 2.5, "end": 3.0},
    ])
    _, stats = smartcut.analyze_silences(transcript, 0.0, 4.0, "en")
    assert stats["silences_removed"] == 1
    assert stats["time_saved"] > 1.0


def test_no_words_in_range_returns_error():
    transcript = _make_transcript([
        {"word": "Hello", "start": 100.0, "end": 100.5},
    ])
    segs, stats = smartcut.analyze_silences(transcript, 0.0, 2.0, "en")
    assert segs == []
    assert "error" in stats


def test_clip_with_no_word_timestamps_returns_no_op():
    transcript = {"segments": [{"text": "Hello world"}]}  # no 'words' field
    segs, _ = smartcut.analyze_silences(transcript, 0.0, 2.0, "en")
    assert segs == []


def test_segments_are_merged_when_close():
    """Segments separated by less than 0.1s should fuse into one."""
    transcript = _make_transcript([
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.55, "end": 1.0},
        {"word": "c", "start": 1.05, "end": 1.5},
    ])
    segs, stats = smartcut.analyze_silences(transcript, 0.0, 2.0, "en")
    # No silences or fillers — single merged segment expected
    assert stats["segments"] == 1


# ---------------------------------------------------------------------------
# Cache plumbing
# ---------------------------------------------------------------------------

def test_clip_lock_returns_same_lock_per_path():
    l1 = smartcut._clip_lock("/tmp/foo.mp4")
    l2 = smartcut._clip_lock("/tmp/foo.mp4")
    assert l1 is l2


def test_clip_lock_different_paths():
    l1 = smartcut._clip_lock("/tmp/foo.mp4")
    l2 = smartcut._clip_lock("/tmp/bar.mp4")
    assert l1 is not l2


def test_segments_hash_is_stable():
    h1 = smartcut._segments_hash([(0.0, 1.0), (2.0, 3.5)], "en")
    h2 = smartcut._segments_hash([(0.0, 1.0), (2.0, 3.5)], "en")
    assert h1 == h2


def test_segments_hash_changes_with_lang():
    h1 = smartcut._segments_hash([(0.0, 1.0)], "en")
    h2 = smartcut._segments_hash([(0.0, 1.0)], "it")
    assert h1 != h2


def test_segments_hash_changes_with_segments():
    h1 = smartcut._segments_hash([(0.0, 1.0)], "en")
    h2 = smartcut._segments_hash([(0.0, 2.0)], "en")
    assert h1 != h2


# ---------------------------------------------------------------------------
# External filler config (optional data/filler_words.json)
# ---------------------------------------------------------------------------

def test_external_filler_config_merges(tmp_path, monkeypatch):
    """If data/filler_words.json exists, its entries should be merged in."""
    # Reset module-level cache so the loader runs again.
    monkeypatch.setattr(smartcut, "_filler_external_loaded", False)

    cfg = tmp_path / "filler_words.json"
    cfg.write_text(json.dumps({"en": ["totally", "literally"]}))
    monkeypatch.setattr(smartcut, "EXTERNAL_FILLER_CONFIG", str(cfg))

    # Save original to restore after this test (avoid leaking into other tests)
    original_en = set(smartcut.FILLER_WORDS["en"])
    try:
        fillers, _ = smartcut._build_filler_index("en")
        assert "totally" in fillers
        assert "literally" in fillers
    finally:
        smartcut.FILLER_WORDS["en"] = original_en
        monkeypatch.setattr(smartcut, "_filler_external_loaded", True)


def test_external_filler_config_missing_is_silent(monkeypatch):
    """Missing config file should not raise."""
    monkeypatch.setattr(smartcut, "_filler_external_loaded", False)
    monkeypatch.setattr(smartcut, "EXTERNAL_FILLER_CONFIG", "/nonexistent/path.json")
    # Should not raise
    smartcut._load_external_filler_config()


# ---------------------------------------------------------------------------
# Version comparison for --no-cache flag
# ---------------------------------------------------------------------------

def test_ae_supports_no_cache_version_comparison(monkeypatch):
    monkeypatch.setattr(smartcut, "_auto_editor_version", lambda: "30.1.0")
    assert smartcut._ae_supports_no_cache() is True

    monkeypatch.setattr(smartcut, "_auto_editor_version", lambda: "30.0.5")
    assert smartcut._ae_supports_no_cache() is False

    monkeypatch.setattr(smartcut, "_auto_editor_version", lambda: "29.3.1")
    assert smartcut._ae_supports_no_cache() is False

    monkeypatch.setattr(smartcut, "_auto_editor_version", lambda: None)
    assert smartcut._ae_supports_no_cache() is False

    monkeypatch.setattr(smartcut, "_auto_editor_version", lambda: "30.2.0")
    assert smartcut._ae_supports_no_cache() is True
