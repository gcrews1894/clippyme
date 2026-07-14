"""Host tests for clippyme.pipeline.reframe_track — the pure tracking classes.

This module deliberately has NO cv2/torch/mediapipe imports, so these run on
the dev host. They pin the exact crop-box math that the aspect_ratio
constructor threading (ex reframe.ASPECT_RATIO global) touches.
"""
import pytest

from clippyme.pipeline.reframe_track import (
    DetectionSmoother,
    SmoothedCameraman,
    SpeakerTracker,
)


# --- SmoothedCameraman crop dimensions per aspect ----------------------------

def test_crop_dims_9_16_default():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)  # default aspect_ratio=9/16
    assert cam.max_crop_height == 1080
    assert cam.max_crop_width == int(1080 * 9 / 16)  # 607 — full-height window
    assert cam.min_crop_height == int(1080 / 1.6)
    assert cam.min_crop_width == int(cam.min_crop_height * 9 / 16)


def test_crop_dims_square():
    cam = SmoothedCameraman(1080, 1080, 1920, 1080, aspect_ratio=1.0)
    assert (cam.max_crop_width, cam.max_crop_height) == (1080, 1080)


def test_crop_dims_16_9_full_frame():
    cam = SmoothedCameraman(1920, 1080, 1920, 1080, aspect_ratio=16 / 9)
    # 16:9 crop of a 16:9 source is the whole frame.
    assert (cam.max_crop_width, cam.max_crop_height) == (1920, 1080)


def test_crop_dims_16_9_on_narrow_source_clamps_width():
    # Source narrower than the target: width clamps, height rederives.
    cam = SmoothedCameraman(1920, 1080, 1280, 1080, aspect_ratio=16 / 9)
    assert cam.max_crop_width == 1280
    assert cam.max_crop_height == int(1280 / (16 / 9))


def test_crop_box_stays_in_bounds_at_edges():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    # Aim far outside the frame; the box must clamp inside the source.
    cam.update_target((1900, 1000, 200, 200))
    x1, y1, x2, y2 = cam.get_crop_box(force_snap=True)
    assert 0 <= x1 < x2 <= 1920
    assert 0 <= y1 < y2 <= 1080
    assert (x2 - x1) <= cam.max_crop_width + 1


def test_crop_box_at_respects_zoom_and_bounds():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    x1, y1, x2, y2 = cam.crop_box_at(960, 540, 1.0)
    assert (x2 - x1) in (cam.max_crop_width, cam.max_crop_width - 1)
    zx1, zy1, zx2, zy2 = cam.crop_box_at(960, 540, 1.6)
    assert (zx2 - zx1) < (x2 - x1)  # tighter crop when zoomed
    assert 0 <= zx1 < zx2 <= 1920 and 0 <= zy1 < zy2 <= 1080


def test_force_snap_jumps_to_target():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    cam.update_target((800, 100, 200, 300))  # face at cx=900, safely in-bounds
    cam.get_crop_box(force_snap=True)
    assert cam.current_center_x == pytest.approx(900.0)


def test_snap_near_edge_clamps_center_to_half_crop_width():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    cam.update_target((100, 100, 200, 300))  # face at cx=200, near left edge
    cam.get_crop_box(force_snap=True)
    # Center clamps to half the (zoomed) crop width so the box stays in-frame.
    assert cam.current_center_x == pytest.approx(cam.crop_width / 2)


def test_person_box_aims_at_head_zone_without_zoom():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    cam.update_target((500, 100, 200, 800), is_person_box=True)
    assert cam.target_center_y == pytest.approx(100 + 800 * 0.15)
    assert cam.target_zoom == 1.0


def test_lost_subject_drifts_back_to_center():
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    cam.lost_hold_frames = 3
    cam.update_target((0, 0, 100, 100))  # park the target far left
    cam.get_crop_box(force_snap=True)
    parked = cam.target_center_x
    for _ in range(20):  # well past the hold window with no fresh target
        cam.get_crop_box()
    assert cam.target_center_x > parked  # eased back toward source center


# --- DetectionSmoother --------------------------------------------------------

def test_detection_smoother_averages_jitter():
    sm = DetectionSmoother(window_size=5)
    boxes = [[100, 100, 50, 50], [104, 100, 50, 50], [96, 100, 50, 50]]
    out = None
    for i, b in enumerate(boxes):
        out = sm.smooth([{"box": list(b), "score": 1.0}], i)
    assert out[0]["box"][0] == int((100 + 104 + 96) / 3)


def test_detection_smoother_reset_drops_history():
    sm = DetectionSmoother(window_size=5)
    sm.smooth([{"box": [100, 100, 50, 50], "score": 1.0}], 0)
    sm.reset()
    assert sm.histories == {} and sm.last_seen_frame == {}
    # After reset a new detection is passed through un-averaged.
    out = sm.smooth([{"box": [500, 100, 50, 50], "score": 1.0}], 1)
    assert out[0]["box"][0] == 500


# --- SpeakerTracker -----------------------------------------------------------

def _face(x, mar):
    return {"box": [x, 100, 100, 100], "score": 100 * 100, "mar": mar}


def test_speaker_tracker_locks_onto_talking_mouth():
    st = SpeakerTracker(cooldown_frames=5)
    # Two faces: left mouth still (mar constant), right mouth oscillating.
    for frame in range(30):
        mar_right = 0.1 if frame % 2 == 0 else 0.6
        box = st.get_target([_face(200, 0.3), _face(1500, mar_right)], frame, 1920)
    assert box is not None
    assert box[0] == 1500  # the talking face wins


def test_speaker_tracker_cooldown_prevents_instant_switch():
    st = SpeakerTracker(cooldown_frames=1000)
    for frame in range(10):
        st.get_target([_face(200, 0.5 if frame % 2 else 0.1)], frame, 1920)
    locked = st.active_speaker_id
    # A brand-new louder face cannot steal the lock inside the cooldown.
    box = st.get_target([_face(200, 0.1), _face(1500, 0.9)], 11, 1920)
    assert st.active_speaker_id == locked
    assert box is None or box[0] == 200


def test_speaker_tracker_reset_forgets_identities():
    st = SpeakerTracker(cooldown_frames=5)
    for frame in range(10):
        st.get_target([_face(200, 0.5 if frame % 2 else 0.1)], frame, 1920)
    assert st.active_speaker_id is not None
    st.reset(frame_number=10)
    assert st.active_speaker_id is None and st.known_faces == []


# --- rule-of-thirds headroom ----------------------------------------------------

def test_face_target_places_eyes_at_headroom_fraction(monkeypatch):
    monkeypatch.delenv("REFRAME_HEADROOM_Y", raising=False)
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    cam.update_target((800, 400, 200, 200))  # mid-frame face, no clamping
    crop_h = cam.max_crop_height / cam.target_zoom
    eyes_y = 400 + 0.40 * 200
    crop_top = cam.target_center_y - crop_h / 2
    assert (eyes_y - crop_top) / crop_h == pytest.approx(0.42)


def test_headroom_half_restores_legacy_centering(monkeypatch):
    monkeypatch.setenv("REFRAME_HEADROOM_Y", "0.5")
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    cam.update_target((800, 400, 200, 200))
    assert cam.target_center_y == pytest.approx(400 + 200 / 2)  # exact legacy


def test_headroom_env_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("REFRAME_HEADROOM_Y", "not-a-number")
    cam = SmoothedCameraman(608, 1080, 1920, 1080)
    assert cam.headroom_y == pytest.approx(0.42)


# --- IoU identity association ---------------------------------------------------

def test_detection_smoother_keeps_stacked_faces_distinct():
    """Two faces at the same x but different y (grid call) must hold separate
    tracks — the old center-x-only matching merged them into one blended box."""
    sm = DetectionSmoother(window_size=5)
    a, b = [100, 100, 80, 80], [100, 500, 80, 80]
    out = None
    for i in range(3):
        out = sm.smooth([{"box": list(a), "score": 1.0},
                         {"box": list(b), "score": 1.0}], i)
    assert len(sm.histories) == 2
    assert out[0]["box"][1] == 100 and out[1]["box"][1] == 500  # never blended


def test_detection_smoother_tracks_moving_box_via_overlap():
    sm = DetectionSmoother(window_size=5)
    sm.smooth([{"box": [100, 100, 100, 100], "score": 1.0}], 0)
    sm.smooth([{"box": [130, 105, 100, 100], "score": 1.0}], 1)  # big overlap
    assert len(sm.histories) == 1  # same identity, matched by IoU


def test_detection_smoother_fast_mover_matched_by_center_distance():
    sm = DetectionSmoother(window_size=5)
    sm.smooth([{"box": [100, 100, 100, 100], "score": 1.0}], 0)
    # Jumped past any overlap, but the center moved <2 widths → same track.
    sm.smooth([{"box": [250, 100, 100, 100], "score": 1.0}], 1)
    assert len(sm.histories) == 1


def _face_at(x, y, mar):
    return {"box": [x, y, 100, 100], "score": 100 * 100, "mar": mar}


def test_speaker_tracker_stacked_faces_get_distinct_ids():
    """Same-x faces stacked vertically must not share an identity (and thus
    must not pool their MAR history / sticky bonus)."""
    st = SpeakerTracker(cooldown_frames=5)
    for frame in range(10):
        st.get_target([_face_at(200, 100, 0.3),
                       _face_at(200, 800, 0.1 if frame % 2 else 0.6)], frame, 1920)
    assert len(st.known_faces) == 2
    assert st.next_id == 2  # exactly two identities ever created


def test_speaker_tracker_moving_face_keeps_identity():
    st = SpeakerTracker(cooldown_frames=5)
    st.get_target([_face_at(200, 100, 0.3)], 0, 1920)
    st.get_target([_face_at(240, 110, 0.3)], 1, 1920)  # overlaps its last box
    assert len(st.known_faces) == 1
    assert st.next_id == 1
