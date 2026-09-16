"""Unit tests for the pure iris-offset geometry (no camera/model)."""

import numpy as np

from gesture_os.gaze import (
    Face,
    NoseOffsetTracker,
    WinkClickDetector,
    detect_wink,
    draw_debug_overlay,
    eye_blink_scores,
    iris_offset,
    nose_offset,
)


def _face(overrides: dict[int, tuple[float, float]]) -> Face:
    """Build a Face with all 478 landmarks at a neutral position except the
    ones given in `overrides` (landmark id -> (x, y))."""
    landmarks = [(0.5, 0.5, 0.0)] * 478
    for idx, (x, y) in overrides.items():
        landmarks[idx] = (x, y, 0.0)
    return Face(landmarks=landmarks)


def _blink_face(left: float, right: float) -> Face:
    """A Face with only blink blendshape scores set; landmarks are
    irrelevant to eye_blink_scores/detect_wink so left empty."""
    return Face(landmarks=[], blendshapes={"eyeBlinkLeft": left, "eyeBlinkRight": right})


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


def test_nose_centered_between_eyes_gives_zero_offset():
    face = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.5)})
    x, y = nose_offset(face)
    assert x == 0.0
    assert y == 0.0


def test_nose_shifted_toward_larger_x_eye_is_positive_x():
    # Nose tip pushed a full eye-span/2 past the eye midpoint, toward the
    # larger-x eye corner (263 here) -> offset of exactly 1.0.
    face = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.6, 0.5)})
    x, y = nose_offset(face)
    assert x == 1.0
    assert y == 0.0


def test_nose_offset_alone_is_never_zero_at_a_neutral_pose():
    # Regression check for the root cause: the nose tip sits below eye
    # level on every face, so raw nose_offset's y is always positive at any
    # normal, "looking straight ahead" pose — this is exactly why
    # NoseOffsetTracker exists (below), not a fixed formula.
    face = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.6)})  # nose below eye line
    _, y = nose_offset(face)
    assert y > 0.0


def test_nose_offset_tracker_reads_zero_at_its_own_first_baseline():
    face = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.6)})  # same "neutral" pose as above
    tracker = NoseOffsetTracker()

    x, y = tracker.read(face)

    assert x == 0.0
    assert y == 0.0


def test_nose_offset_tracker_reports_movement_relative_to_baseline():
    neutral = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.6)})
    tilted_down = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.8)})  # nose moved further down
    tracker = NoseOffsetTracker()

    tracker.read(neutral)  # establishes the baseline
    x, y = tracker.read(tilted_down)

    assert x == 0.0
    assert y > 0.0  # only the *change* from neutral, not the constant anatomical bias


def test_nose_offset_tracker_recenter_captures_a_fresh_baseline():
    face_a = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.6)})
    face_b = _face({33: (0.4, 0.5), 263: (0.6, 0.5), 1: (0.5, 0.8)})
    tracker = NoseOffsetTracker()

    tracker.read(face_a)
    assert tracker.read(face_b) != (0.0, 0.0)

    tracker.recenter()
    assert tracker.read(face_b) == (0.0, 0.0)  # face_b is now the new baseline


def test_eye_blink_scores_reads_named_blendshapes():
    face = _blink_face(left=0.8, right=0.1)
    assert eye_blink_scores(face) == (0.8, 0.1)


def test_eye_blink_scores_defaults_to_zero_without_blendshapes():
    face = Face(landmarks=[])  # blendshapes not requested/available
    assert eye_blink_scores(face) == (0.0, 0.0)


def test_detect_wink_left_eye_alone_closed():
    face = _blink_face(left=0.9, right=0.1)
    assert detect_wink(face, threshold=0.5) == "left"


def test_detect_wink_right_eye_alone_closed():
    face = _blink_face(left=0.1, right=0.9)
    assert detect_wink(face, threshold=0.5) == "right"


def test_detect_wink_both_eyes_open_is_not_a_wink():
    face = _blink_face(left=0.1, right=0.1)
    assert detect_wink(face, threshold=0.5) is None


def test_detect_wink_both_eyes_closed_is_an_ordinary_blink_not_a_wink():
    # This is the key distinction the feature is built around: a normal
    # blink closes both eyes together and must NOT register as a click.
    face = _blink_face(left=0.9, right=0.9)
    assert detect_wink(face, threshold=0.5) is None


def test_wink_click_detector_fires_once_on_the_frame_a_wink_begins():
    detector = WinkClickDetector()
    winking = _blink_face(left=0.9, right=0.1)

    assert detector.update(winking, threshold=0.5) == "left"


def test_wink_click_detector_does_not_repeat_while_held():
    detector = WinkClickDetector()
    winking = _blink_face(left=0.9, right=0.1)

    detector.update(winking, threshold=0.5)  # first frame: fires
    assert detector.update(winking, threshold=0.5) is None  # still held: doesn't
    assert detector.update(winking, threshold=0.5) is None  # still held: doesn't


def test_wink_click_detector_fires_again_after_release_and_re_wink():
    detector = WinkClickDetector()
    winking = _blink_face(left=0.9, right=0.1)
    open_eyes = _blink_face(left=0.1, right=0.1)

    assert detector.update(winking, threshold=0.5) == "left"
    assert detector.update(open_eyes, threshold=0.5) is None  # released
    assert detector.update(winking, threshold=0.5) == "left"  # wink again: fires


def test_draw_debug_overlay_marks_iris_pixel():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    face = _face({468: (0.2, 0.7)})  # left iris at a distinctive, asymmetric spot

    draw_debug_overlay(frame, face)

    assert tuple(frame[70, 20]) == (255, 0, 0)  # frame is indexed [row=y, col=x]


def test_draw_debug_overlay_marks_nose_tip_pixel():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    face = _face({1: (0.3, 0.9)})  # nose tip at a distinctive, asymmetric spot

    draw_debug_overlay(frame, face)

    assert tuple(frame[90, 30]) == (0, 0, 255)  # frame is indexed [row=y, col=x]
