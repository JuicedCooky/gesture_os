"""Unit tests for the pure deadzone helper and CursorController.move."""

import pyautogui

from gesture_os.actions import CursorController, _apply_deadzone


def test_value_inside_deadzone_is_zeroed():
    assert _apply_deadzone(0.1, deadzone=0.15) == 0.0


def test_value_outside_deadzone_passes_through():
    assert _apply_deadzone(0.3, deadzone=0.15) == 0.3


def test_negative_value_is_compared_by_magnitude():
    assert _apply_deadzone(-0.1, deadzone=0.15) == 0.0
    assert _apply_deadzone(-0.3, deadzone=0.15) == -0.3


def test_move_scales_each_axis_by_its_own_sensitivity(monkeypatch):
    calls = []
    monkeypatch.setattr(pyautogui, "moveRel", lambda dx, dy: calls.append((dx, dy)))

    cursor = CursorController(deadzone=0.0)
    cursor.move(0.5, 0.25, sensitivity_x=10.0, sensitivity_y=40.0)

    assert calls == [(5.0, 10.0)]


def test_move_negative_sensitivity_inverts_that_axis_direction(monkeypatch):
    calls = []
    monkeypatch.setattr(pyautogui, "moveRel", lambda dx, dy: calls.append((dx, dy)))

    cursor = CursorController(deadzone=0.0)
    cursor.move(0.5, 0.5, sensitivity_x=-10.0, sensitivity_y=10.0)

    assert calls == [(-5.0, 5.0)]


def test_move_respects_deadzone_per_axis(monkeypatch):
    calls = []
    monkeypatch.setattr(pyautogui, "moveRel", lambda dx, dy: calls.append((dx, dy)))

    cursor = CursorController(deadzone=0.2)
    cursor.move(0.1, 0.5, sensitivity_x=100.0, sensitivity_y=100.0)  # x inside deadzone

    assert calls == [(0.0, 50.0)]
