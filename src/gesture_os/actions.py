"""Maps recognized gestures/gaze to OS-level actions via pyautogui."""

from __future__ import annotations

from collections.abc import Callable

import pyautogui

GestureAction = Callable[[], None]


def default_action_map() -> dict[str, GestureAction]:
    """The built-in gesture -> OS action bindings.

    Empty for now — `point`/`peace` are unbound (previously volume up/down,
    removed) and `fist`/`open_palm` are bound in `GestureOsApp` instead, to
    pause/resume gaze cursor control, which needs access to app state a
    stateless action map can't hold.
    """
    return {}


class ActionDispatcher:
    """Runs the action bound to a gesture, ignoring unmapped/unknown ones."""

    def __init__(self, action_map: dict[str, GestureAction] | None = None) -> None:
        self.action_map = default_action_map() if action_map is None else action_map

    def dispatch(self, gesture: str) -> bool:
        """Run the action for `gesture`. Returns whether one was found."""
        action = self.action_map.get(gesture)
        if action is None:
            return False
        action()
        return True


def _apply_deadzone(value: float, deadzone: float) -> float:
    """Zero out small values so gaze jitter near center doesn't move the cursor."""
    return 0.0 if abs(value) < deadzone else value


class CursorController:
    """Moves the OS mouse cursor from an iris offset (see gaze.py).

    `move_to()` is the primary mode: an absolute screen position from a
    fitted `GazeCalibration` (see calibration.py) — "look here, cursor goes
    here." `move()` is the uncalibrated fallback used before a calibration
    exists: a *relative* (joystick-style) nudge of `offset * sensitivity`
    pixels per call, since raw offsets alone aren't precise enough for an
    absolute mapping without calibration. `sensitivity`/`deadzone` only
    affect that fallback.
    """

    def __init__(self, sensitivity: float = 20.0, deadzone: float = 0.15) -> None:
        self.sensitivity = sensitivity
        self.deadzone = deadzone

    def move(self, offset_x: float, offset_y: float) -> None:
        """Uncalibrated fallback: nudge the cursor relative to where it is."""
        dx = _apply_deadzone(offset_x, self.deadzone) * self.sensitivity
        dy = _apply_deadzone(offset_y, self.deadzone) * self.sensitivity
        if dx or dy:
            pyautogui.moveRel(dx, dy)

    def move_to(self, x: int, y: int) -> None:
        """Calibrated mode: move the cursor to an absolute screen position."""
        pyautogui.moveTo(x, y)
