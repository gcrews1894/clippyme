"""Host tests for reframe_ops.follow_debounced_path — the subject-mode camera.

Pins the dead-zone / settle-debounce / edge-trigger behaviour that replaces the
continuous Savitzky-Golay pan for subject (FrameShift) scenes: hold still while
the subject stays central, wait for it to settle before re-centring, but snap to
follow immediately when it nears the crop edge. Pure math (cv2-free) → runs on
the host tier.
"""
import pytest

from clippyme.pipeline import reframe_ops as ro


def _obj(cx):
    return (float(cx), 500.0, 1.0)  # cy / zoom pass through unchanged


# crop_w=500, x_max=1000 → half=250, bounds [250,750]; dead radius 0.5*250=125,
# edge radius 0.8*250=200.

def test_follow_static_subject_holds_still():
    out = ro.follow_debounced_path([_obj(500)] * 20, [0] * 20, crop_w=500, x_max=1000)
    assert all(o[0] == pytest.approx(500.0) for o in out)
    assert out[0][1] == 500.0 and out[0][2] == 1.0  # cy/zoom pass through


def test_follow_holds_while_subject_stays_in_dead_zone():
    # cam inits on the first sample (500); a 100px offset is inside the 125 dead
    # radius → the camera must not move.
    out = ro.follow_debounced_path([_obj(500)] + [_obj(600)] * 10, [0] * 11,
                                   crop_w=500, x_max=1000)
    assert all(o[0] == pytest.approx(500.0) for o in out)


def test_follow_does_not_chase_a_moving_subject():
    # Subject oscillates through the debounce band and back through centre; it
    # never settles, so the camera holds.
    targets = [_obj(500), _obj(660)] * 12
    out = ro.follow_debounced_path(targets, [0] * len(targets), crop_w=500,
                                   x_max=1000, settle_frames=8)
    assert all(o[0] == pytest.approx(500.0) for o in out)


def test_follow_recenters_once_subject_settles():
    # Jump off-centre into the band and stop; after ~settle_frames the camera
    # eases toward the subject — but only until the subject re-enters the
    # dead-zone (it brings the subject back into the comfortable zone, it does
    # not chase it to dead-centre).
    targets = [_obj(500)] * 2 + [_obj(660)] * 40
    out = ro.follow_debounced_path(targets, [0] * len(targets), crop_w=500,
                                   x_max=1000, settle_frames=8, follow_rate=0.2)
    xs = [o[0] for o in out]
    assert xs[3] == pytest.approx(500.0)      # still holding right after the jump
    assert xs[-1] > 520.0                      # eventually eased in toward the subject
    assert xs[-1] <= 660.0 + 1e-6              # never overshoots the subject
    # Eased in exactly until the subject sits back inside the dead radius (125).
    assert 660.0 - xs[-1] <= 125.0 + 1e-6


def test_follow_snaps_immediately_near_the_edge():
    # A jump past the edge margin (200) follows on the SAME frame, no settle wait.
    targets = [_obj(500)] * 2 + [_obj(720)] * 6
    out = ro.follow_debounced_path(targets, [0] * len(targets), crop_w=500,
                                   x_max=1000, settle_frames=8, edge_rate=0.5)
    assert out[1][0] == pytest.approx(500.0)
    assert out[2][0] == pytest.approx(610.0)   # 500 + 220*0.5 on the edge frame


def test_follow_resets_camera_at_scene_cut():
    targets = [_obj(500)] * 5 + [_obj(800)] * 5
    sids = [0] * 5 + [1] * 5
    out = ro.follow_debounced_path(targets, sids, crop_w=500, x_max=1000)
    assert out[4][0] == pytest.approx(500.0)   # scene 0 held at 500
    assert out[5][0] == pytest.approx(750.0)   # scene 1 snaps onto 800 → clamped to hi


def test_follow_clamps_camera_to_frame_bounds():
    out = ro.follow_debounced_path([_obj(980)] * 5, [0] * 5, crop_w=500, x_max=1000)
    assert all(250.0 <= o[0] <= 750.0 for o in out)


def test_follow_preserves_none_and_length():
    targets = [None, _obj(500), None, _obj(500)]
    out = ro.follow_debounced_path(targets, [0, 0, 0, 0], crop_w=500, x_max=1000)
    assert len(out) == 4
    assert out[0] is None and out[2] is None
    assert out[1][0] == pytest.approx(500.0)


def test_follow_degenerate_crop_centers():
    # Source narrower than the crop → render letterboxes anyway; cam = centre.
    out = ro.follow_debounced_path([_obj(100)] * 3, [0] * 3, crop_w=1200, x_max=1000)
    assert all(o[0] == pytest.approx(500.0) for o in out)
