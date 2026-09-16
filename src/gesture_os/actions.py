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
    """Moves the OS mouse cursor from a gaze offset (see gaze.py).

    `move_to()` is the primary mode: an absolute screen position from a
    fitted `GazeCalibration` (see calibration.py) — "look here, cursor goes
    here." `move()` is the fallback (available any time via the "Relative"
    movement-mode toggle, not just before a calibration exists): a
    *relative* (joystick-style) nudge of `offset * sensitivity` pixels per
    call, with `sensitivity_x`/`sensitivity_y` passed in per call rather
    than fixed at construction, since the right value differs per tracking
    source (iris vs. nose — see settings.py, which persists them) and a
    negative value inverts that axis' direction.
    """

    def __init__(self, deadzone: float = 0.15) -> None:
        self.deadzone = deadzone

    def move(
        self, offset_x: float, offset_y: float, sensitivity_x: float, sensitivity_y: float
    ) -> None:
        """Nudge the cursor relative to where it is."""
        dx = _apply_deadzone(offset_x, self.deadzone) * sensitivity_x
        dy = _apply_deadzone(offset_y, self.deadzone) * sensitivity_y
        if dx or dy:
            pyautogui.moveRel(dx, dy)

    def move_to(self, x: int, y: int) -> None:
        """Calibrated mode: move the cursor to an absolute screen position."""
        pyautogui.moveTo(x, y)
