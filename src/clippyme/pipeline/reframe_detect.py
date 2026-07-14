"""ML-bound detection layer for the reframe pipeline (cv2 + YOLO + MediaPipe).

Owns the lazy model singletons (YOLOv8n, MediaPipe FaceDetection/FaceMesh) and
the per-frame detectors. Split out of ``reframe.py`` so the pure tracking
classes (``reframe_track``) stay host-importable; ``reframe.py`` re-exports
these names for back-compat.
"""
import os
import re

import cv2
import mediapipe as mp
from ultralytics import YOLO

from clippyme.pipeline.hardware import DEVICE

_yolo_model = None

# REFRAME_YOLO_MODEL allowlist: known ultralytics weight names only, so the env
# var can trade accuracy for latency (yolov8n → s/m, or yolo11n/s) but can
# never point YOLO at an arbitrary filesystem path or URL. yolov8n.pt is the
# Dockerfile-pre-downloaded default; anything else is a lazy ~20-50MB download
# on first use and 2-3x slower per frame on CPU.
_YOLO_MODEL_RE = re.compile(r"^yolo(v8[nsm]|11[ns])\.pt$")


def _get_yolo_model():
    """Lazy-load the YOLO body/object model on first detection call.

    The variant is selectable via REFRAME_YOLO_MODEL (allowlisted, default
    yolov8n.pt); an unrecognised value falls back to the default rather than
    erroring mid-render.
    """
    global _yolo_model
    if _yolo_model is None:
        name = (os.getenv("REFRAME_YOLO_MODEL") or "").strip().lower()
        if not _YOLO_MODEL_RE.match(name):
            name = 'yolov8n.pt'
        _yolo_model = YOLO(name)
        _yolo_model.to(DEVICE)
    return _yolo_model

mp_face_detection = mp.solutions.face_detection
mp_face_mesh = mp.solutions.face_mesh

_face_detection = None
_face_mesh = None


def _get_face_detection():
    """Lazy-init MediaPipe FaceDetection on first use (avoids ~300ms TFLite
    load at import time on every subprocess, incl. --reframe-only switches)."""
    global _face_detection
    if _face_detection is None:
        _face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)
    return _face_detection


def _get_face_mesh():
    """Lazy-init MediaPipe FaceMesh on first use (see _get_face_detection)."""
    global _face_mesh
    if _face_mesh is None:
        _face_mesh = mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    return _face_mesh

# MediaPipe FaceMesh mouth landmark indices (inner lips + corners). Defined here
# because compute_mouth_aspect_ratio was extracted from main.py during the
# refactor; without these the MAR call raised NameError on every frame, silently
# disabling active-speaker selection (the exception was swallowed by the
# corrupt-frame guard → ~37% duplicated frames).
_MOUTH_TOP = 13
_MOUTH_BOTTOM = 14
_MOUTH_LEFT = 78
_MOUTH_RIGHT = 308


def compute_mouth_aspect_ratio(frame_bgr, face_box) -> float | None:
    """
    Crops the face region and runs FaceMesh to extract the Mouth Aspect Ratio
    (vertical mouth opening / horizontal mouth width).

    Returns a normalized MAR in [0, ~1.5] or None if landmarks couldn't be
    extracted (e.g. profile view, occlusion). The absolute value matters less
    than its *variance over time* — a still mouth has near-zero variance, a
    talking mouth oscillates.
    """
    x, y, w, h = face_box
    H, W = frame_bgr.shape[:2]
    # Pad the crop a bit so FaceMesh has context
    pad = int(max(w, h) * 0.2)
    x1 = max(0, int(x - pad))
    y1 = max(0, int(y - pad))
    x2 = min(W, int(x + w + pad))
    y2 = min(H, int(y + h + pad))
    if x2 - x1 < 30 or y2 - y1 < 30:
        return None
    roi = frame_bgr[y1:y2, x1:x2]
    rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    rgb.flags.writeable = False
    res = _get_face_mesh().process(rgb)
    if not res.multi_face_landmarks:
        return None
    lm = res.multi_face_landmarks[0].landmark
    rh, rw = roi.shape[:2]
    top = (lm[_MOUTH_TOP].x * rw, lm[_MOUTH_TOP].y * rh)
    bot = (lm[_MOUTH_BOTTOM].x * rw, lm[_MOUTH_BOTTOM].y * rh)
    left = (lm[_MOUTH_LEFT].x * rw, lm[_MOUTH_LEFT].y * rh)
    right = (lm[_MOUTH_RIGHT].x * rw, lm[_MOUTH_RIGHT].y * rh)
    mouth_h = ((top[0] - bot[0]) ** 2 + (top[1] - bot[1]) ** 2) ** 0.5
    mouth_w = ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
    if mouth_w < 1:
        return None
    return mouth_h / mouth_w

def _face_conf_floor() -> float:
    """REFRAME_FACE_CONF — minimum detection confidence for a face candidate.

    Default 0.5 matches the FaceDetection model's own min_detection_confidence,
    so no candidate is filtered unless the knob is raised. Empty-safe."""
    raw = (os.getenv("REFRAME_FACE_CONF") or "").strip()
    try:
        return float(raw) if raw else 0.5
    except ValueError:
        return 0.5


def detect_face_candidates(frame):
    """
    Returns list of all detected faces using lightweight FaceDetection.

    Each candidate carries its detection ``confidence`` and a ``score`` of
    area x confidence — so a large low-confidence false positive no longer
    outranks a small real face in scene classification and speaker
    size-weighting. Candidates below REFRAME_FACE_CONF are dropped.
    """
    height, width, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = _get_face_detection().process(rgb_frame)

    candidates = []

    if not results.detections:
        return []

    conf_floor = _face_conf_floor()
    for detection in results.detections:
        try:
            confidence = float(detection.score[0])
        except (IndexError, TypeError, ValueError):
            confidence = 1.0
        if confidence < conf_floor:
            continue
        bboxC = detection.location_data.relative_bounding_box
        x = int(bboxC.xmin * width)
        y = int(bboxC.ymin * height)
        w = int(bboxC.width * width)
        h = int(bboxC.height * height)

        candidates.append({
            'box': [x, y, w, h],
            'score': w * h * confidence,  # area weighted by detection confidence
            'confidence': confidence,
        })

    return candidates

def detect_person_yolo(frame):
    """
    Fallback: Detect largest person using YOLO when face detection fails.
    Returns [x, y, w, h] of the person's 'upper body' approximation.
    """
    results = _get_yolo_model()(frame, verbose=False, classes=[0])  # class 0 is person
    
    if not results:
        return None
        
    best_box = None
    max_area = 0
    
    for result in results:
        boxes = result.boxes
        for box in boxes:
            x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
            w = x2 - x1
            h = y2 - y1
            area = w * h
            
            if area > max_area:
                max_area = area
                # Return the full person bbox. SmoothedCameraman.update_target
                # applies the head-zone offset itself when is_person_box=True
                # (y_center = y + h*0.15). Previously we truncated here AND
                # there, which stacked the offsets and aimed above the head.
                best_box = [x1, y1, w, h]
                
    return best_box
