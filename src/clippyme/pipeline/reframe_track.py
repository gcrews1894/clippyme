"""Pure tracking/camera classes for the reframe pipeline.

No cv2/torch/mediapipe imports — plain python + the pure math in
``reframe_ops`` — so this module is host-importable and host-unit-tested
(``tests/pipeline/test_reframe_track.py``). ``reframe.py`` re-exports these
names for back-compat.

``SmoothedCameraman`` takes the output aspect ratio as an explicit
constructor argument (default 9/16). It used to read the removed
``reframe.ASPECT_RATIO`` module global that ``main`` set per-job.
"""
import os
from collections import deque

from clippyme.pipeline.reframe_ops import (
    OneEuroFilter,
    advance_value_with_velocity,
    asymmetric_zoom_step,
    box_iou,
    drift_to_center,
    headroom_center_y,
    limit_step,
    zoom_for_face_height,
)

class DetectionSmoother:
    """
    Applies temporal smoothing (rolling average) to face detection bounding boxes.
    Reduces micro-jitter from frame-to-frame detection noise.
    """
    def __init__(self, window_size=5):
        self.window_size = window_size
        self.histories = {}  # face_id -> deque of (x, y, w, h)
        self.last_seen_frame: dict[int, int] = {}

    def smooth(self, candidates, frame_number):
        """
        Takes raw face candidates and returns smoothed versions.
        candidates: list of {'box': [x,y,w,h], 'score': float, ...}
        """
        smoothed = []
        for cand in candidates:
            x, y, w, h = cand['box']
            cx = x + w / 2
            # Identity association: spatial overlap (IoU) first — far stronger
            # than the old center-x proximity rule, which merged faces stacked
            # at the same x (grid calls) and blended crossing subjects' box
            # histories. The fallback for fast movers whose boxes no longer
            # overlap between (even-frame) detections uses the full 2-D center
            # distance — x-only distance would re-merge the stacked faces the
            # IoU match just kept apart.
            cy = y + h / 2
            best_id = None
            best_iou = 0.3  # minimum overlap to claim an existing track
            for fid, hist in self.histories.items():
                if hist:
                    iou = box_iou((x, y, w, h), hist[-1])
                    if iou > best_iou:
                        best_iou = iou
                        best_id = fid
            if best_id is None:
                min_dist = float('inf')
                for fid, hist in self.histories.items():
                    if hist:
                        last = hist[-1]
                        dist = ((cx - (last[0] + last[2] / 2)) ** 2
                                + (cy - (last[1] + last[3] / 2)) ** 2) ** 0.5
                        if dist < min_dist and dist < w * 2:
                            min_dist = dist
                            best_id = fid
            if best_id is None:
                best_id = frame_number * 1000 + len(smoothed)
            # Update history
            if best_id not in self.histories:
                self.histories[best_id] = deque(maxlen=self.window_size)
            self.histories[best_id].append((x, y, w, h))
            self.last_seen_frame[best_id] = frame_number
            # Average
            hist = self.histories[best_id]
            avg_x = int(sum(b[0] for b in hist) / len(hist))
            avg_y = int(sum(b[1] for b in hist) / len(hist))
            avg_w = int(sum(b[2] for b in hist) / len(hist))
            avg_h = int(sum(b[3] for b in hist) / len(hist))
            smoothed.append({**cand, 'box': [avg_x, avg_y, avg_w, avg_h]})
        # Prune tracks not seen in the last 60 frames (~2s @ 30 fps).
        stale = [fid for fid, last in self.last_seen_frame.items()
                 if frame_number - last > 60]
        for fid in stale:
            self.histories.pop(fid, None)
            self.last_seen_frame.pop(fid, None)
        return smoothed

    def reset(self):
        """Drop all track history — call at a hard scene cut.

        A face in the new scene that happens to land near a previous scene's
        track would otherwise be averaged with up to window_size-1 stale boxes
        from an unrelated shot, blending two people's positions for several
        frames right after the cut.
        """
        self.histories.clear()
        self.last_seen_frame.clear()

class SmoothedCameraman:
    """
    Handles smooth camera movement with adaptive exponential easing.

    The camera accelerates toward the target and decelerates as it approaches,
    mimicking a professional human operator. Smoothing is *adaptive*:
      - Tiny moves (inside safe zone): zero motion (dead-band, kills jitter).
      - Small/medium moves: gentle 0.08 glide (cinematic).
      - Large moves (>60% of crop width away, e.g. speaker switch on opposite
        side): aggressive 0.30 catch-up so the camera doesn't visibly drift
        for a full second.

    This kills the "software-glide" feel on rapid speaker switches inside a
    single PySceneDetect scene, while preserving the smooth feel for normal
    head movement.
    """
    SMOOTHING_SLOW = 0.08   # cinematic glide for small/medium moves
    SMOOTHING_FAST = 0.30   # aggressive catch-up for large jumps
    FAST_THRESHOLD_RATIO = 0.6  # diff > this * crop_width → use fast smoothing
    # Asymmetric zoom rates (ported from smart-reframe): push IN slowly for a
    # cinematic feel, pull BACK fast so a growing face / arriving second person
    # is never left chopped while the crop catches up.
    ZOOM_RATE_IN = 0.05     # zooming in (tighter crop) — slow
    ZOOM_RATE_OUT = 0.12    # pulling back (wider crop) — fast

    def __init__(self, output_width, output_height, video_width, video_height,
                 *, aspect_ratio: float = 9 / 16):
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height
        self.aspect_ratio = float(aspect_ratio)

        # Max crop dimensions (full source height = the widest possible 9:16 frame)
        self.max_crop_height = video_height
        self.max_crop_width = int(self.max_crop_height * self.aspect_ratio)
        if self.max_crop_width > video_width:
            self.max_crop_width = video_width
            self.max_crop_height = int(self.max_crop_width / self.aspect_ratio)

        # Min crop dimensions (zoom-in cap: never zoom past 1.6x to avoid mush)
        self.min_crop_height = int(self.max_crop_height / 1.6)
        self.min_crop_width = int(self.min_crop_height * self.aspect_ratio)

        # Current crop dims (will animate between min and max)
        self.crop_width = self.max_crop_width
        self.crop_height = self.max_crop_height

        # Initial centers (geometric center of source)
        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2
        self.current_center_y = video_height / 2
        self.target_center_y = video_height / 2

        # Target zoom factor (1.0 = max crop, 1.6 = max zoom). Animates over time.
        self.current_zoom = 1.0
        self.target_zoom = 1.0

        # Safe zones (dead-band to kill jitter). Tunable via env (fraction of the
        # max crop dimension). The old X=0.20 default let a talking head drift up
        # to 20% off-center before the camera reacted, which read as poor framing
        # on single-speaker shots. Measured sweep on a real clip (tmp/reframe_eval)
        # found X=0.05 / Y=0.08 cut centering error ~30% with *lower* jerk (tighter
        # tracking, not jitter), so those are the new defaults; raise to loosen.
        self.safe_zone_radius_x = self.max_crop_width * float(os.getenv("REFRAME_DEADZONE_X", "0.05"))
        self.safe_zone_radius_y = self.max_crop_height * float(os.getenv("REFRAME_DEADZONE_Y", "0.08"))

        # Lost-subject recovery: when no target arrives for a while (speaker
        # leaves / long occlusion), hold then ease back to the source center
        # instead of freezing the camera on empty space. Always on — strictly
        # safer than the old freeze behavior.
        self.frames_since_target = 0
        self.lost_hold_frames = int(os.getenv("REFRAME_LOST_HOLD", "90"))
        self.lost_drift_rate = float(os.getenv("REFRAME_LOST_DRIFT", "0.05"))

        # Optional 1€ adaptive smoother (opt-in via REFRAME_SMOOTHER=euro).
        # Default keeps the proven two-speed EMA. The 1€ path follows fast
        # moves and damps jitter with a single principled tradeoff; enable it
        # to A/B test camera feel in an environment where output can be viewed.
        _smoother = os.getenv("REFRAME_SMOOTHER", "").strip().lower()
        self._use_euro = _smoother == "euro"
        self._use_spring = _smoother == "spring"
        if self._use_euro:
            mc = float(os.getenv("REFRAME_EURO_MINCUTOFF", "0.014"))
            beta = float(os.getenv("REFRAME_EURO_BETA", "0.0008"))
            self._euro_x = OneEuroFilter(min_cutoff=mc, beta=beta)
            self._euro_y = OneEuroFilter(min_cutoff=mc, beta=beta)

        # Optional momentum / damped-spring smoother (REFRAME_SMOOTHER=spring):
        # carries velocity for operator-like accel/decel, with a hard per-frame
        # velocity cap. Ported from KazKozDev/auto-vertical-reframe.
        if self._use_spring:
            self._spring_resp = float(os.getenv("REFRAME_SPRING_RESPONSE", "0.18"))
            self._spring_damp = float(os.getenv("REFRAME_SPRING_DAMPING", "0.82"))
            self._vx = 0.0
            self._vy = 0.0

        # Rule-of-thirds headroom: place the subject's eye line at this
        # fraction of the crop height instead of dead-center (pro framing puts
        # eyes ~1/3 from the top; the reframe research doc calls this the #1
        # low-cost win). 0.42 matches the eval scorer's TARGET_Y; 0.5 restores
        # the legacy centered framing exactly. Empty-safe like the other knobs.
        _hy = (os.getenv("REFRAME_HEADROOM_Y") or "").strip()
        try:
            self.headroom_y = float(_hy) if _hy else 0.42
        except ValueError:
            self.headroom_y = 0.42

        # Hard per-frame pan-rate cap in px (applies to every smoother mode).
        # 0 disables it (default). Also caps the spring's max velocity.
        self._max_step_px = float(os.getenv("REFRAME_MAX_STEP_PX", "0"))
        self._spring_maxv = self._max_step_px if self._max_step_px > 0 else self.max_crop_width * 0.05

    def update_target(self, face_box, is_person_box: bool = False):
        """
        Updates target center + target zoom based on a detected face or person box.

        face_box: (x, y, w, h) in source coordinates.
        is_person_box: if True, treat the box as a YOLO person bbox (full body)
                       and aim at the *upper portion* (head zone) instead of
                       the geometric center. Fixes the "camera shows knees"
                       bug from the old YOLO fallback.
        """
        if not face_box:
            return
        # A real target this frame → reset the lost-subject counter.
        self.frames_since_target = 0
        x, y, w, h = face_box
        self.target_center_x = x + w / 2

        if is_person_box:
            # Head is roughly in the top 20% of a standing person bbox
            self.target_center_y = y + h * 0.15
            # Person fallback = no clean face → don't zoom in (could be wide group)
            self.target_zoom = 1.0
        else:
            # Zoom in proportionally to face size — small faces (talking head in
            # wide shot) trigger more zoom; large faces stay at 1.0. Continuous
            # face-occupancy target (ported from smart-reframe) replaces the old
            # 4-bucket ladder, which snapped visibly at bucket edges. 1.6 ceiling
            # matches min_crop (= max_crop/1.6); face aims for ~40% of crop height.
            self.target_zoom = zoom_for_face_height(
                h, self.max_crop_height, target_occupancy=0.4,
                min_zoom=1.0, max_zoom=1.6,
            )
            # Vertical target uses rule-of-thirds headroom at the crop height
            # this zoom implies. REFRAME_HEADROOM_Y=0.5 is the exact legacy
            # centering (not routed through the eye-line estimate, so the
            # escape hatch is byte-identical). NB: collapse_scene_targets caps
            # zoom at 1.35 AFTER taking the median cy, so on capped scenes the
            # eyes sit slightly below the target fraction — accepted inaccuracy.
            if self.headroom_y == 0.5:
                self.target_center_y = y + h / 2
            else:
                crop_h = self.max_crop_height / self.target_zoom
                self.target_center_y = headroom_center_y(
                    y, h, crop_h, self.video_height, target_frac=self.headroom_y,
                )

    def _ease_axis(self, current: float, target: float, safe_radius: float, fast_ref: float) -> float:
        """Adaptive easing for a single axis. Returns the new current value."""
        diff = target - current
        abs_diff = abs(diff)
        if abs_diff <= safe_radius:
            return current  # dead-band
        if abs_diff > fast_ref * self.FAST_THRESHOLD_RATIO:
            return current + diff * self.SMOOTHING_FAST
        return current + diff * self.SMOOTHING_SLOW

    def get_crop_box(self, force_snap=False):
        """
        Returns (x1, y1, x2, y2) for the current frame.

        Tracks both X and Y axes with adaptive easing, and animates zoom level
        based on detected face size. Crop dimensions are recomputed each frame
        from the current zoom factor.
        """
        if force_snap:
            self.current_center_x = self.target_center_x
            self.current_center_y = self.target_center_y
            self.current_zoom = self.target_zoom
            self.frames_since_target = 0
            if self._use_euro:
                self._euro_x.reset()
                self._euro_y.reset()
            if self._use_spring:
                self._vx = 0.0
                self._vy = 0.0
        else:
            # Lost-subject recovery: once we've gone `lost_hold_frames` without
            # a fresh target, ease the TARGET toward the source center (and
            # gently zoom out). Normal easing below then glides the camera
            # there smoothly. Active in TRACK/WIDE only (GENERAL/DISABLED set
            # centers directly and never call this).
            self.frames_since_target += 1
            if self.frames_since_target > self.lost_hold_frames:
                self.target_center_x = drift_to_center(
                    self.target_center_x, self.video_width / 2,
                    self.frames_since_target, self.lost_hold_frames, self.lost_drift_rate)
                self.target_center_y = drift_to_center(
                    self.target_center_y, self.video_height / 2,
                    self.frames_since_target, self.lost_hold_frames, self.lost_drift_rate)
                if self.target_zoom > 1.0:
                    self.target_zoom = max(1.0, self.target_zoom - 0.01)

            prev_center_x, prev_center_y = self.current_center_x, self.current_center_y
            if self._use_euro:
                # Apply the dead-band on the target, then 1€-filter every frame
                # (feeding the filter each frame keeps its velocity estimate live).
                tx = self.target_center_x if abs(self.target_center_x - self.current_center_x) > self.safe_zone_radius_x else self.current_center_x
                ty = self.target_center_y if abs(self.target_center_y - self.current_center_y) > self.safe_zone_radius_y else self.current_center_y
                self.current_center_x = self._euro_x.filter(tx, 1.0)
                self.current_center_y = self._euro_y.filter(ty, 1.0)
            elif self._use_spring:
                # Dead-band, then integrate a velocity-damped move toward target.
                tx = self.target_center_x if abs(self.target_center_x - self.current_center_x) > self.safe_zone_radius_x else self.current_center_x
                ty = self.target_center_y if abs(self.target_center_y - self.current_center_y) > self.safe_zone_radius_y else self.current_center_y
                self.current_center_x, self._vx = advance_value_with_velocity(
                    self.current_center_x, tx, self._vx,
                    self._spring_resp, self._spring_damp, self._spring_maxv)
                self.current_center_y, self._vy = advance_value_with_velocity(
                    self.current_center_y, ty, self._vy,
                    self._spring_resp, self._spring_damp, self._spring_maxv)
            else:
                self.current_center_x = self._ease_axis(
                    self.current_center_x, self.target_center_x,
                    self.safe_zone_radius_x, self.max_crop_width,
                )
                self.current_center_y = self._ease_axis(
                    self.current_center_y, self.target_center_y,
                    self.safe_zone_radius_y, self.max_crop_height,
                )
            # Hard per-frame pan-rate cap (all modes; off when 0). Guarantees the
            # camera never jumps more than REFRAME_MAX_STEP_PX px in one frame.
            if self._max_step_px > 0:
                self.current_center_x = limit_step(prev_center_x, self.current_center_x, self._max_step_px)
                self.current_center_y = limit_step(prev_center_y, self.current_center_y, self._max_step_px)
            # Zoom animates more slowly than position to feel cinematic, and
            # asymmetrically: fast pull-back, slow push-in (smart-reframe port).
            if abs(self.target_zoom - self.current_zoom) > 0.01:
                self.current_zoom = asymmetric_zoom_step(
                    self.current_zoom, self.target_zoom,
                    self.ZOOM_RATE_IN, self.ZOOM_RATE_OUT,
                )

        # Recompute crop dims from current zoom
        self.crop_width = max(self.min_crop_width, int(self.max_crop_width / self.current_zoom))
        self.crop_height = max(self.min_crop_height, int(self.max_crop_height / self.current_zoom))

        # Clamp center inside the source frame
        half_w = self.crop_width / 2
        half_h = self.crop_height / 2

        cx = max(half_w, min(self.video_width - half_w, self.current_center_x))
        cy = max(half_h, min(self.video_height - half_h, self.current_center_y))
        self.current_center_x = cx
        self.current_center_y = cy

        x1 = max(0, int(cx - half_w))
        x2 = min(self.video_width, int(cx + half_w))
        y1 = max(0, int(cy - half_h))
        y2 = min(self.video_height, int(cy + half_h))

        return x1, y1, x2, y2

    def crop_box_at(self, cx: float, cy: float, zoom: float):
        """Crop box (x1, y1, x2, y2) for an explicit center + zoom, with no
        easing. Used by the two-stage global-smoothing render pass, which feeds
        in a pre-smoothed trajectory instead of letting the camera ease online.
        Shares the exact crop-dim + clamp math of ``get_crop_box``.
        """
        crop_width = max(self.min_crop_width, int(self.max_crop_width / zoom))
        crop_height = max(self.min_crop_height, int(self.max_crop_height / zoom))
        half_w = crop_width / 2
        half_h = crop_height / 2
        cx = max(half_w, min(self.video_width - half_w, cx))
        cy = max(half_h, min(self.video_height - half_h, cy))
        x1 = max(0, int(cx - half_w))
        x2 = min(self.video_width, int(cx + half_w))
        y1 = max(0, int(cy - half_h))
        y2 = min(self.video_height, int(cy + half_h))
        return x1, y1, x2, y2

class SpeakerTracker:
    """
    Tracks speakers over time to prevent rapid switching and handle temporary
    obstructions. Uses Mouth Aspect Ratio (MAR) variance as the primary signal
    for active-speaker detection — a person whose mouth is moving (high MAR
    variance over the last ~1s window) is far more likely to be speaking than
    one whose mouth is still, regardless of face size.
    """
    MAR_WINDOW_SIZE = 25  # ~1s @ 25fps of MAR samples per speaker
    SIZE_WEIGHT = 0.3     # face size still contributes (proximity to camera)
    MOUTH_WEIGHT = 1.0    # mouth motion is the dominant signal

    def __init__(self, cooldown_frames=30):
        self.active_speaker_id = None
        self.speaker_scores = {}  # {id: smoothed_score}
        self.mar_history = {}     # {id: [mar0, mar1, ...]} sliding window
        self.last_seen = {}
        self.locked_counter = 0

        # Hyperparameters
        self.switch_cooldown = cooldown_frames
        self.last_switch_frame = -1000

        # ID tracking
        self.next_id = 0
        self.known_faces = []  # [{'id': 0, 'center': x, 'box': [x,y,w,h], 'last_frame': 123}]

    def reset(self, frame_number=None):
        """Forget speaker identities and scores — call at a hard scene cut.

        Faces on either side of a cut are different people even when they land
        at similar x positions; carrying identities across lets the previous
        scene's active speaker keep its 3x sticky bonus and the switch
        cooldown, suppressing the lock onto the actual new speaker for up to
        ~cooldown_frames. Also rearms the cooldown so the new scene can pick
        its speaker immediately. ``next_id`` keeps counting so IDs never
        collide across scenes.
        """
        self.active_speaker_id = None
        self.speaker_scores = {}
        self.mar_history = {}
        self.last_seen = {}
        self.locked_counter = 0
        self.known_faces = []
        if frame_number is not None:
            self.last_switch_frame = frame_number - self.switch_cooldown

    def get_target(self, face_candidates, frame_number, width):
        """
        Decides which face to focus on.

        face_candidates: list of {'box': [x,y,w,h], 'score': float, 'mar': float|None}
          - 'score' is face area x detection confidence (used for size weighting)
          - 'mar' is mouth aspect ratio at this frame (None if not extractable)
        """
        current_candidates = []

        # 1. Match faces to known IDs — IoU (spatial overlap) first, center
        # proximity as the fallback for fast movers whose boxes no longer
        # overlap between detection frames. The old center-x-only rule merged
        # faces stacked at the same x (grid calls) and let crossing subjects
        # swap IDs — stealing the 3x sticky bonus and the MAR history. The
        # fallback uses the full 2-D center distance for the same reason.
        for face in face_candidates:
            x, y, w, h = face['box']
            center_x = x + w / 2
            center_y = y + h / 2

            best_match_id = -1
            best_iou = 0.1  # minimum overlap to claim an existing identity
            for kf in self.known_faces:
                if frame_number - kf['last_frame'] > 30:
                    continue
                last_box = kf.get('box')
                if not last_box:
                    continue
                iou = box_iou(face['box'], last_box)
                if iou > best_iou:
                    best_iou = iou
                    best_match_id = kf['id']

            if best_match_id == -1:
                min_dist = width * 0.15
                for kf in self.known_faces:
                    if frame_number - kf['last_frame'] > 30:
                        continue
                    last_box = kf.get('box')
                    if last_box:
                        dist = ((center_x - (last_box[0] + last_box[2] / 2)) ** 2
                                + (center_y - (last_box[1] + last_box[3] / 2)) ** 2) ** 0.5
                    else:
                        dist = abs(center_x - kf['center'])
                    if dist < min_dist:
                        min_dist = dist
                        best_match_id = kf['id']

            if best_match_id == -1:
                best_match_id = self.next_id
                self.next_id += 1

            self.known_faces = [kf for kf in self.known_faces if kf['id'] != best_match_id]
            self.known_faces.append({'id': best_match_id, 'center': center_x,
                                     'box': list(face['box']), 'last_frame': frame_number})

            current_candidates.append({
                'id': best_match_id,
                'box': face['box'],
                'score': face['score'],
                'mar': face.get('mar'),
            })

        # 2. Update MAR history (sliding window) for each visible face
        for cand in current_candidates:
            pid = cand['id']
            if cand['mar'] is not None:
                hist = self.mar_history.setdefault(pid, [])
                hist.append(cand['mar'])
                if len(hist) > self.MAR_WINDOW_SIZE:
                    hist.pop(0)

        # Decay smoothed scores; drop stale entries
        for pid in list(self.speaker_scores.keys()):
            self.speaker_scores[pid] *= 0.85
            if self.speaker_scores[pid] < 0.05:
                del self.speaker_scores[pid]
                self.mar_history.pop(pid, None)

        # 3. Compute combined score: mouth-motion variance + face size
        for cand in current_candidates:
            pid = cand['id']
            size_norm = cand['score'] / (width * width * 0.05)

            mar_hist = self.mar_history.get(pid, [])
            if len(mar_hist) >= 5:
                mean = sum(mar_hist) / len(mar_hist)
                variance = sum((m - mean) ** 2 for m in mar_hist) / len(mar_hist)
                # Scale variance to a useful range (0..~3)
                mouth_motion = min(variance * 200.0, 3.0)
            else:
                # Not enough samples yet → fall back to neutral
                mouth_motion = 0.5

            combined = self.SIZE_WEIGHT * size_norm + self.MOUTH_WEIGHT * mouth_motion
            self.speaker_scores[pid] = self.speaker_scores.get(pid, 0) + combined

        # 3. Determine Best Speaker
        if not current_candidates:
            # If no one found, maintain last active speaker if cooldown allows
            # to avoid black screen or jump to 0,0
            return None 
            
        best_candidate = None
        max_score = -1
        
        for cand in current_candidates:
            pid = cand['id']
            total_score = self.speaker_scores.get(pid, 0)
            
            # Hysteresis: HUGE Bonus for current active speaker
            if pid == self.active_speaker_id:
                total_score *= 3.0 # Sticky factor
                
            if total_score > max_score:
                max_score = total_score
                best_candidate = cand

        # 4. Decide Switch
        if best_candidate:
            target_id = best_candidate['id']
            
            if target_id == self.active_speaker_id:
                self.locked_counter += 1
                return best_candidate['box']
            
            # New person
            if frame_number - self.last_switch_frame < self.switch_cooldown:
                old_cand = next((c for c in current_candidates if c['id'] == self.active_speaker_id), None)
                if old_cand:
                    return old_cand['box']
                # Active speaker temporarily off-screen: hold the previous
                # framing (return None → cameraman keeps its current target)
                # instead of switching. Prevents rapid A→B→A oscillation
                # when A briefly turns away / occludes.
                return None

            self.active_speaker_id = target_id
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return best_candidate['box']
            
        return None
