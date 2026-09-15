"""Tkinter desktop UI: shows the webcam feed and drives both input pipelines
(hand gestures and gaze-based cursor movement) from it.

This is the composition root — it is the only module that wires capture,
the recognizer/dispatcher pair, and the gaze tracker/cursor pair together
into one running loop.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import cv2
import pyautogui
from PIL import Image, ImageTk

from gesture_os.actions import ActionDispatcher, CursorController, default_action_map
from gesture_os.calibration import GazeCalibration, load_calibration
from gesture_os.capture import WebcamCapture
from gesture_os.gaze import FaceGazeTracker, draw_debug_overlay, iris_offset
from gesture_os.recognizer import HandGestureRecognizer
from gesture_os.ui.calibration_window import CalibrationWindow

_POLL_MS = 15  # UI tick interval; actual throughput is capped by camera FPS


class GestureOsApp:
    """Owns the Tk root window and the capture/recognize/act loop."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("gesture_os")

        self.video_label = ttk.Label(self.root)
        self.video_label.pack()

        self.status_var = tk.StringVar(value="stopped")
        ttk.Label(self.root, textvariable=self.status_var).pack()
        self.gaze_status_var = tk.StringVar(value="gaze: active")
        ttk.Label(self.root, textvariable=self.gaze_status_var).pack()
        ttk.Button(self.root, text="Calibrate gaze", command=self._start_calibration).pack()

        self.capture = WebcamCapture()
        self.recognizer = HandGestureRecognizer()
        action_map = default_action_map()
        action_map["fist"] = self._pause_gaze_control
        action_map["open_palm"] = self._resume_gaze_control
        self.dispatcher = ActionDispatcher(action_map)
        self.gaze_tracker = FaceGazeTracker()
        self.cursor = CursorController()
        self.calibration: GazeCalibration | None = load_calibration()
        self._last_offset: tuple[float, float] | None = None
        self._gaze_paused = False
        self._running = False

    def start(self) -> None:
        self.capture.open()
        self._running = True
        self.status_var.set("running")
        self._tick()

    def stop(self) -> None:
        self._running = False
        self.capture.close()
        self.status_var.set("stopped")

    def _tick(self) -> None:
        if not self._running:
            return
        frame = self.capture.read()
        if frame is not None:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            for hand in self.recognizer.process(frame_rgb):
                gesture = self.recognizer.classify(hand)
                if self.dispatcher.dispatch(gesture):
                    self.status_var.set(f"running - last gesture: {gesture}")

            face = self.gaze_tracker.process(frame_rgb)
            self._last_offset = iris_offset(face) if face is not None else None
            if self._last_offset is not None:
                if not self._gaze_paused:
                    self._move_cursor(*self._last_offset)
                draw_debug_overlay(frame_rgb, face)

            image = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
            self.video_label.configure(image=image)
            self.video_label.image = image  # keep a reference alive
        self.root.after(_POLL_MS, self._tick)

    def _move_cursor(self, offset_x: float, offset_y: float) -> None:
        try:
            if self.calibration is not None:
                self.cursor.move_to(*self.calibration.to_screen(offset_x, offset_y))
            else:
                self.cursor.move(offset_x, offset_y)  # uncalibrated fallback
        except pyautogui.FailSafeException:
            # User dragged the real mouse to a screen corner: pyautogui's
            # built-in panic button. Actually stop moving the cursor (not
            # just switch modes — the fallback would immediately retrigger
            # this at the same corner) until they make an open_palm gesture.
            self._gaze_paused = True
            self.gaze_status_var.set("gaze: paused (fail-safe triggered)")

    def _pause_gaze_control(self) -> None:
        self._gaze_paused = True
        self.gaze_status_var.set("gaze: paused (fist)")

    def _resume_gaze_control(self) -> None:
        self._gaze_paused = False
        self.gaze_status_var.set("gaze: active (open palm)")

    def _start_calibration(self) -> None:
        CalibrationWindow(
            self.root, get_offset=lambda: self._last_offset, on_complete=self._on_calibrated
        )

    def _on_calibrated(self) -> None:
        self.calibration = load_calibration()
        self.status_var.set("calibrated")

    def run(self) -> None:
        self.start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        self.stop()
        self.recognizer.close()
        self.gaze_tracker.close()
        self.root.destroy()
