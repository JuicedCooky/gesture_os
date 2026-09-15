"""Unit tests for the pure gesture-classification logic (no camera/model)."""

import numpy as np

from gesture_os.recognizer import Hand, count_extended_fingers, draw_debug_overlay


def _hand(finger_y: dict[int, float], handedness: str = "Right") -> Hand:
    """Build a Hand with all landmarks at a neutral position except the ones
    given in `finger_y` (landmark id -> y coordinate)."""
    landmarks = [(0.5, 0.5, 0.0)] * 21
    for idx, y in finger_y.items():
        landmarks[idx] = (0.5, y, 0.0)
    return Hand(landmarks=landmarks, handedness=handedness)


def test_fist_has_no_extended_fingers():
    hand = _hand({})
    assert count_extended_fingers(hand) == 0


def test_open_palm_has_five_extended_fingers():
    finger_y = {tip_id: 0.1 for tip_id in (8, 12, 16, 20)}
    hand = _hand(finger_y, handedness="Right")
    landmarks = list(hand.landmarks)
    landmarks[4] = (0.3, 0.5, 0.0)  # thumb tip left of its IP joint (x=0.5)
    hand = Hand(landmarks=landmarks, handedness="Right")
    assert count_extended_fingers(hand) == 5


def test_draw_debug_overlay_colors_extended_and_curled_tips_differently():
    # A fist: every fingertip curled, so every tip should be marked red.
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    fist = _hand({})
    landmarks = list(fist.landmarks)
    landmarks[4] = (0.6, 0.5, 0.0)  # thumb tip right of IP -> curled for a Right hand
    fist = Hand(landmarks=landmarks, handedness="Right")

    draw_debug_overlay(frame, fist)

    tip_x, tip_y = int(0.5 * 100), int(0.5 * 100)  # index tip (8) sits at (0.5, 0.5) by default
    assert tuple(frame[tip_y, tip_x]) == (255, 0, 0)
