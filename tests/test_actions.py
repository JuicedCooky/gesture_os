"""Unit tests for the pure deadzone helper used by CursorController."""

from gesture_os.actions import _apply_deadzone


def test_value_inside_deadzone_is_zeroed():
    assert _apply_deadzone(0.1, deadzone=0.15) == 0.0


def test_value_outside_deadzone_passes_through():
    assert _apply_deadzone(0.3, deadzone=0.15) == 0.3


def test_negative_value_is_compared_by_magnitude():
    assert _apply_deadzone(-0.1, deadzone=0.15) == 0.0
    assert _apply_deadzone(-0.3, deadzone=0.15) == -0.3
