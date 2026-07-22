"""Source-level guard: subject (FrameShift) mode rides the two-pass smoother.

Subject mode used to recompute its weighted-interest crop independently every
frame — zero temporal smoothing, so flickering detections strobed the crop and
a single dropped detection snapped to letterbox. The fix routes subject mode
through ``_render_global_smooth`` (pass 1 records centers, ``hold_gaps``
bridges short dropouts, per-scene savgol + stationary lock smooths, pass 2
renders), default-on via ``REFRAME_SUBJECT_SMOOTH``.

``reframe.py`` imports cv2/mediapipe/YOLO, so the host tier cannot import it —
these tests PARSE the source (the ``test_reframe_scene_reset.py`` pattern) to
pin the wiring; behaviour is covered by the Docker integration suite and the
pure smoothing math by ``test_reframe_ops.py``.
"""
from pathlib import Path

_PIPELINE = Path(__file__).resolve().parents[2] / "src" / "clippyme" / "pipeline"
REFRAME_PATH = _PIPELINE / "reframe.py"
DETECT_PATH = _PIPELINE / "reframe_detect.py"
MAIN_PATH = _PIPELINE / "main.py"


def _reframe_src():
    return REFRAME_PATH.read_text(encoding="utf-8")


def _detect_src():
    return DETECT_PATH.read_text(encoding="utf-8")


def _main_src():
    return MAIN_PATH.read_text(encoding="utf-8")


def test_subject_mode_gates_into_global_smooth():
    src = _reframe_src()
    assert "reframe_mode == 'subject' and _subject_smooth_enabled()" in src
    assert "def _subject_smooth_enabled" in src


def test_pass1_records_frameshift_centers_and_holds_gaps():
    src = _reframe_src()
    assert "_frameshift_interest_center(frame)" in src
    assert "hold_gaps(object_targets, scene_ids, _subject_hold_frames())" in src


def test_object_scenes_use_the_debounce_follower():
    """Subject scenes follow the dead-zone/settle/edge camera by default, with
    the legacy savgol pan kept behind REFRAME_SUBJECT_FOLLOW for A/B. Routing
    them through collapse_scene_targets (an AUTO policy) is NOT allowed."""
    src = _reframe_src()
    assert "object_smoothed = follow_debounced_path(" in src
    assert "_subject_follow_enabled()" in src
    assert "_subject_follow_params()" in src
    # savgol path is retained as the escape-hatch fallback.
    assert "object_smoothed = build_smoothed_trajectory(" in src


def test_pass2_renders_from_smoothed_center():
    src = _reframe_src()
    assert "_render_frameshift_at(frame, tgt[0]" in src


def test_scene_cut_clears_object_hold():
    """The odd-frame carry (last_object_target) must reset at every hard cut so
    a subject position never bleeds into the next shot."""
    lines = _reframe_src().splitlines()
    advance_lines = [i for i, line in enumerate(lines)
                     if line.strip() == "current_scene_index += 1"]
    assert advance_lines, "scene-advance sites not found — did the loop change?"
    pass1_windows = ["\n".join(lines[i:i + 12]) for i in advance_lines]
    assert any("last_object_target = None" in w for w in pass1_windows), \
        "pass-1 scene advance does not clear last_object_target"


def test_legacy_per_frame_path_is_kept():
    """REFRAME_SUBJECT_SMOOTH=0 escape hatch: the streaming loop must still be
    able to call the per-frame create_frameshift_frame composition."""
    src = _reframe_src()
    assert "create_frameshift_frame(" in src


def test_face_candidates_carry_detection_confidence():
    src = _detect_src()
    assert "detection.score" in src
    assert "REFRAME_FACE_CONF" in src
    assert "'confidence': confidence" in src


def test_yolo_model_env_is_allowlisted():
    src = _detect_src()
    assert "REFRAME_YOLO_MODEL" in src
    assert "_YOLO_MODEL_RE" in src


def test_main_translates_subject_flags_to_env():
    """main.py must turn the --no-subject-smooth / --subject-hold CLI flags into
    the REFRAME_SUBJECT_SMOOTH / REFRAME_SUBJECT_HOLD env vars that reframe.py
    reads at call time (the --model / --language pattern), and persist them for
    /api/reframe reuse."""
    src = _main_src()
    assert "--no-subject-smooth" in src
    assert "--subject-hold" in src
    assert 'os.environ["REFRAME_SUBJECT_SMOOTH"] = "0"' in src
    assert 'os.environ["REFRAME_SUBJECT_HOLD"]' in src
    # Persisted beside 'aspect' for post-hoc re-reframe.
    assert "clips_data['subject_smooth']" in src
