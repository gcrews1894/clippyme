"""Tests for the main.py performance optimizations (Phase 2).

main.py imports cv2/scenedetect/mediapipe at module load, so this whole
module is skipped on hosts without the heavy CV runtime and runs inside the
Docker backend image.
"""
import pytest

pytest.importorskip("scenedetect")
pytestmark = pytest.mark.integration

from clippyme.pipeline import main as m


def test_whisper_model_is_cached_per_config(monkeypatch):
    """_get_whisper_model must construct a model once per (name, device,
    compute_type) and return the cached instance on subsequent calls."""
    calls = []

    class FakeModel:
        def __init__(self, name, device=None, compute_type=None):
            calls.append((name, device, compute_type))

    # faster_whisper is imported lazily inside _get_whisper_model.
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(m, "_whisper_models", {})

    a = m._get_whisper_model("base", "cpu", "int8")
    b = m._get_whisper_model("base", "cpu", "int8")
    assert a is b
    assert len(calls) == 1  # constructed exactly once

    # A different config constructs a second, distinct model.
    c = m._get_whisper_model("base", "cuda", "float16")
    assert c is not a
    assert len(calls) == 2
