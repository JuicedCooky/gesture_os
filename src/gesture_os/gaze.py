"""Face landmark detection (MediaPipe Tasks) and gaze/head-pose offsets.

Same two-layer split as recognizer.py:

- `iris_offset` and `nose_offset` are pure geometry over landmark
  coordinates, unit-testable with synthetic landmark data (see
  tests/test_gaze.py). They're two alternative, interchangeable signal
  sources for cursor control — `ui/app.py` lets the user pick between them
  at runtime — sharing the same (x, y) roughly-[-1, 1] shape so either can
  feed `CursorController`/`GazeCalibration` unchanged.
- `FaceGazeTracker` wraps the actual MediaPipe `FaceLandmarker` task and
  feeds its output through whichever pure function is selected.
- `NoseOffsetTracker` sits in front of `nose_offset` specifically: unlike
  iris tracking, raw nose position has no natural zero (see its docstring),
  so it reports offset relative to a captured baseline instead of the raw
  reading.

`draw_debug_overlay` is a third, separate thing: MediaPipe has no built-in
display of its own (it only returns landmarks), so this draws the points
both offset functions read directly onto the frame ui/app.py already shows,
to make tracking stability visible rather than inferred from cursor jitter.

Landmark indices below are MediaPipe's canonical 478-point face mesh
(468 face points + 10 iris points, always present on this task's output).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

# <repo root>/models/face_landmarker.task — fetched by scripts/download_models.py.
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "face_landmarker.task"

Point = tuple[float, float, float]
EyeLandmarkIds = tuple[int, int, int, int, int]

# (iris_center, outer_corner, inner_corner, top_lid, bottom_lid)
_LEFT_EYE: EyeLandmarkIds = (468, 33, 133, 159, 145)
_RIGHT_EYE: EyeLandmarkIds = (473, 263, 362, 386, 374)

_IRIS_IDS = (_LEFT_EYE[0], _RIGHT_EYE[0])
_EYE_SOCKET_IDS = _LEFT_EYE[1:] + _RIGHT_EYE[1:]

# Canonical MediaPipe face-mesh indices: nose tip, and each eye's outer
# corner (used here as a face-scale reference, not eye-socket sizing).
_NOSE_TIP = 1
_LEFT_EYE_OUTER = _LEFT_EYE[1]
_RIGHT_EYE_OUTER = _RIGHT_EYE[1]


@dataclass(frozen=True)
class Face:
    """A single detected face's landmarks, normalized to [0, 1] image coords."""

    landmarks: list[Point]


def _eye_offset(lm: list[Point], eye: EyeLandmarkIds) -> tuple[float, float]:
    iris_id, outer_id, inner_id, top_id, bottom_id = eye
    iris, outer = lm[iris_id], lm[outer_id]
    inner, top, bottom = lm[inner_id], lm[top_id], lm[bottom_id]

    width = abs(outer[0] - inner[0])
    height = abs(bottom[1] - top[1])
    if width == 0 or height == 0:
        return 0.0, 0.0

    center_x = (outer[0] + inner[0]) / 2
    center_y = (top[1] + bottom[1]) / 2
    return (iris[0] - center_x) / (width / 2), (iris[1] - center_y) / (height / 2)


def iris_offset(face: Face) -> tuple[float, float]:
    """Iris position within the eye socket, averaged over both eyes.

    Returns (x, y) roughly in [-1, 1], (0, 0) centered, in raw (unmirrored)
    image-coordinate directions: positive x is toward larger image x
    (image-right), positive y toward larger image y (down). Both eyes move
    conjugately for a real gaze shift, so their offsets share this sign
    convention and averaging them reinforces rather than cancels the signal.
    Purely geometric — no smoothing or calibration, both of which belong in
    the caller (see CursorController).
    """
    lx, ly = _eye_offset(face.landmarks, _LEFT_EYE)
    rx, ry = _eye_offset(face.landmarks, _RIGHT_EYE)
    return (lx + rx) / 2, (ly + ry) / 2


def nose_offset(face: Face) -> tuple[float, float]:
    """Head-pose proxy: nose-tip position relative to the midpoint between
    the eyes' outer corners, normalized by that inter-eye distance (a
    face-scale unit that stays roughly constant as the user moves closer to
    or farther from the camera).

    Same (x, y) roughly-[-1, 1] shape and sign convention as `iris_offset`
    (positive x toward larger image x, positive y toward larger image y) —
    a drop-in alternative signal. Moving your head is a coarser, steadier
    motion than moving just your eyes, at the cost of needing head movement
    rather than only a glance to move the cursor.
    """
    lm = face.landmarks
    nose = lm[_NOSE_TIP]
    left_eye, right_eye = lm[_LEFT_EYE_OUTER], lm[_RIGHT_EYE_OUTER]

    eye_span = abs(right_eye[0] - left_eye[0])
    if eye_span == 0:
        return 0.0, 0.0

    center_x = (left_eye[0] + right_eye[0]) / 2
    center_y = (left_eye[1] + right_eye[1]) / 2
    return (nose[0] - center_x) / (eye_span / 2), (nose[1] - center_y) / (eye_span / 2)


class NoseOffsetTracker:
    """Turns `nose_offset` into a proper head-pose *movement* signal.

    `nose_offset` alone has no natural zero: the nose tip sits physically
    below eye level on every face, so its y-component is a constant
    positive bias rather than a pitch signal that crosses zero at rest —
    in relative mode (no calibration step to absorb a constant bias into an
    intercept, unlike absolute mode) that reads as "always moves down."
    There's no fixed anatomical reference that reads exactly zero at a
    neutral pose across different faces/camera framings, so instead this
    captures whatever `nose_offset` reads on the first call as a baseline
    and reports the *delta* from it from then on — the same idea real
    head-tracking mouse tools use ("recenter").
    """

    def __init__(self) -> None:
        self._baseline: tuple[float, float] | None = None

    def read(self, face: Face) -> tuple[float, float]:
        """Nose offset relative to the baseline, capturing one if needed."""
        raw_x, raw_y = nose_offset(face)
        if self._baseline is None:
            self._baseline = (raw_x, raw_y)
        base_x, base_y = self._baseline
        return raw_x - base_x, raw_y - base_y

    def recenter(self) -> None:
        """Discards the baseline so the next `read()` captures a fresh one —
        call this when the user has shifted position and "centered" no
        longer means what it used to."""
        self._baseline = None


def draw_debug_overlay(frame_rgb, face: Face) -> None:
    """Draws the landmarks both `iris_offset` and `nose_offset` read,
    directly on `frame_rgb` in place (RGB channel order, matching the frame
    ui/app.py displays) — red dot on each iris, green dots on the eye-socket
    landmarks used to size/center it, blue dot on the nose tip — so tracking
    quality is visible in the UI itself rather than inferred from how the
    cursor moves. Drawn regardless of which signal is currently selected.
    """
    height, width = frame_rgb.shape[:2]

    def pixel(idx: int) -> tuple[int, int]:
        x, y, _ = face.landmarks[idx]
        return int(x * width), int(y * height)

    for idx in _EYE_SOCKET_IDS:
        cv2.circle(frame_rgb, pixel(idx), 2, (0, 255, 0), thickness=-1)
    for idx in _IRIS_IDS:
        cv2.circle(frame_rgb, pixel(idx), 4, (255, 0, 0), thickness=-1)
    cv2.circle(frame_rgb, pixel(_NOSE_TIP), 4, (0, 0, 255), thickness=-1)


class FaceGazeTracker:
    """Wraps MediaPipe's FaceLandmarker task to produce iris offsets."""

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        min_detection_confidence: float = 0.5,
    ) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Face landmark model not found at {model_path}. "
                "Run `python scripts/download_models.py` to fetch it."
            )
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=min_detection_confidence,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, frame_rgb) -> Face | None:
        """Run detection on an RGB frame and return the face found, if any."""
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # VIDEO mode requires strictly increasing timestamps; see recognizer.py.
        timestamp_ms = max(time.monotonic_ns() // 1_000_000, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        result = self._landmarker.detect_for_video(image, timestamp_ms)
        if not result.face_landmarks:
            return None
        points = [(p.x, p.y, p.z) for p in result.face_landmarks[0]]
        return Face(landmarks=points)

    def close(self) -> None:
        self._landmarker.close()
