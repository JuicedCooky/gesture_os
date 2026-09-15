"""Unit tests for the pure iris-offset geometry (no camera/model)."""

import numpy as np

from gesture_os.gaze import Face, draw_debug_overlay, iris_offset


def _face(overrides: dict[int, tuple[float, float]]) -> Face:
    """Build a Face with all 478 landmarks at a neutral position except the
    ones given in `overrides` (landmark id -> (x, y))."""
    landmarks = [(0.5, 0.5, 0.0)] * 478
    for idx, (x, y) in overrides.items():
        landmarks[idx] = (x, y, 0.0)
    return Face(landmarks=landmarks)


def _eye_landmarks(
    iris_id: int, outer_id: int, inner_id: int, top_id: int, bottom_id: int, iris_xy
):
    return {
        outer_id: (0.4, 0.5),
        inner_id: (0.6, 0.5),
        top_id: (0.5, 0.4),
        bottom_id: (0.5, 0.6),
        iris_id: iris_xy,
    }


def test_centered_iris_gives_zero_offset():
    overrides = {}
    overrides.update(_eye_landmarks(468, 33, 133, 159, 145, (0.5, 0.5)))
    overrides.update(_eye_landmarks(473, 263, 362, 386, 374, (0.5, 0.5)))
    face = _face(overrides)
    x, y = iris_offset(face)
    assert x == 0.0
    assert y == 0.0


def test_iris_shifted_toward_larger_x_corner_is_positive_x():
    # Both eyes' corners are set up identically (outer at x=0.4, inner at
    # x=0.6), so the larger-x corner is the same "inner" landmark in both
    # tuples here — the offset sign only depends on relative position, not
    # which corner is labeled inner/outer (see iris_offset's docstring).
    overrides = {}
    overrides.update(_eye_landmarks(468, 33, 133, 159, 145, (0.6, 0.5)))
    overrides.update(_eye_landmarks(473, 263, 362, 386, 374, (0.6, 0.5)))
    face = _face(overrides)
    x, y = iris_offset(face)
    assert x == 1.0
    assert y == 0.0


def test_draw_debug_overlay_marks_iris_pixel():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    face = _face({468: (0.2, 0.7)})  # left iris at a distinctive, asymmetric spot

    draw_debug_overlay(frame, face)

    assert tuple(frame[70, 20]) == (255, 0, 0)  # frame is indexed [row=y, col=x]
