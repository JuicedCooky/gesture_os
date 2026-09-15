"""Fullscreen gaze-calibration flow.

Shows one target dot at a time; the user looks at it and presses SPACE to
capture an iris-offset sample at that known screen point. Once every target
has a sample, fits and saves a GazeCalibration (see calibration.py).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from gesture_os.calibration import CalibrationSample, fit_calibration, save_calibration

# Normalized (0-1) screen positions for a 5-point calibration: center + corners.
# Corners are inset slightly so the target dot itself stays fully on screen.
_TARGETS = [(0.5, 0.5), (0.08, 0.08), (0.92, 0.08), (0.08, 0.92), (0.92, 0.92)]

GetOffset = Callable[[], "tuple[float, float] | None"]


class CalibrationWindow:
    """Owns a fullscreen Toplevel that walks through `_TARGETS`.

    `get_offset` is called with no arguments each time the user presses
    SPACE, and must return the current iris_offset() reading, or None if no
    face is detected right now (in which case that keypress is ignored and
    the same target stays up). `on_complete` runs once calibration is saved.
    """

    def __init__(
        self, root: tk.Misc, get_offset: GetOffset, on_complete: Callable[[], None]
    ) -> None:
        self._get_offset = get_offset
        self._on_complete = on_complete
        self._samples: list[CalibrationSample] = []
        self._index = 0

        self.window = tk.Toplevel(root)
        self.window.attributes("-fullscreen", True)
        self.window.configure(bg="black")
        self.window.focus_force()
        self.screen_width = self.window.winfo_screenwidth()
        self.screen_height = self.window.winfo_screenheight()

        self.canvas = tk.Canvas(self.window, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            self.screen_width // 2,
            40,
            fill="white",
            text="Look at the dot and press SPACE (Esc to cancel)",
            font=("Segoe UI", 16),
        )
        self.dot = self.canvas.create_oval(0, 0, 0, 0, fill="red", outline="")

        self.window.bind("<space>", self._capture)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self._show_target()

    def _target_screen_point(self) -> tuple[int, int]:
        norm_x, norm_y = _TARGETS[self._index]
        return round(norm_x * self.screen_width), round(norm_y * self.screen_height)

    def _show_target(self) -> None:
        x, y = self._target_screen_point()
        radius = 14
        self.canvas.coords(self.dot, x - radius, y - radius, x + radius, y + radius)

    def _capture(self, _event: object) -> None:
        offset = self._get_offset()
        if offset is None:
            return  # no face detected right now; let them try again
        self._samples.append(
            CalibrationSample(offset=offset, screen_point=self._target_screen_point())
        )
        self._index += 1
        if self._index >= len(_TARGETS):
            calibration = fit_calibration(self._samples, self.screen_width, self.screen_height)
            save_calibration(calibration)
            self.window.destroy()
            self._on_complete()
        else:
            self._show_target()
