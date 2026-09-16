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
from gesture_os.gaze import FaceGazeTracker, NoseOffsetTracker, iris_offset
from gesture_os.gaze import draw_debug_overlay as draw_gaze_overlay
from gesture_os.recognizer import HandGestureRecognizer
from gesture_os.recognizer import draw_debug_overlay as draw_hand_overlay
from gesture_os.settings import AxisSensitivity, Settings, load_settings, save_settings
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

        self.tracking_source_var = tk.StringVar(value="iris")
        source_frame = ttk.LabelFrame(self.root, text="Tracking source")
        source_frame.pack(fill="x", padx=4, pady=2)
        ttk.Radiobutton(
            source_frame, text="Iris", variable=self.tracking_source_var, value="iris"
        ).pack(side="left")
        ttk.Radiobutton(
            source_frame, text="Face / nose", variable=self.tracking_source_var, value="nose"
        ).pack(side="left")
        ttk.Button(
            source_frame, text="Recenter head position", command=self._recenter_nose_tracking
        ).pack(side="left")
        self.nose_tracker = NoseOffsetTracker()

        self.movement_mode_var = tk.StringVar(value="absolute")
        movement_frame = ttk.LabelFrame(self.root, text="Movement mode")
        movement_frame.pack(fill="x", padx=4, pady=2)
        ttk.Radiobutton(
            movement_frame, text="Absolute (calibrated)", variable=self.movement_mode_var,
            value="absolute",
        ).pack(side="left")
        ttk.Radiobutton(
            movement_frame, text="Relative (dx/dy)", variable=self.movement_mode_var,
            value="relative",
        ).pack(side="left")

        self.settings = load_settings()
        self.iris_x_var = tk.DoubleVar(value=self.settings.iris.x)
        self.iris_y_var = tk.DoubleVar(value=self.settings.iris.y)
        self.nose_x_var = tk.DoubleVar(value=self.settings.nose.x)
        self.nose_y_var = tk.DoubleVar(value=self.settings.nose.y)
        sensitivity_frame = ttk.LabelFrame(self.root, text="Relative movement sensitivity")
        sensitivity_frame.pack(fill="x", padx=4, pady=2)
        self._add_sensitivity_row(sensitivity_frame, "Iris X", self.iris_x_var)
        self._add_sensitivity_row(sensitivity_frame, "Iris Y", self.iris_y_var)
        self._add_sensitivity_row(sensitivity_frame, "Nose X", self.nose_x_var)
        self._add_sensitivity_row(sensitivity_frame, "Nose Y", self.nose_y_var)
        self.sensitivity_status_var = tk.StringVar(value="")
        ttk.Button(
            sensitivity_frame, text="Save sensitivity", command=self._save_sensitivity
        ).pack(side="left")
        ttk.Label(sensitivity_frame, textvariable=self.sensitivity_status_var).pack(side="left")

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
                draw_hand_overlay(frame_rgb, hand)

            face = self.gaze_tracker.process(frame_rgb)
            if face is not None:
                if self.tracking_source_var.get() == "nose":
                    self._last_offset = self.nose_tracker.read(face)
                else:
                    self._last_offset = iris_offset(face)
            else:
                self._last_offset = None
            if self._last_offset is not None:
                if not self._gaze_paused:
                    self._move_cursor(*self._last_offset)
                draw_gaze_overlay(frame_rgb, face)

            image = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
            self.video_label.configure(image=image)
            self.video_label.image = image  # keep a reference alive
        self.root.after(_POLL_MS, self._tick)

    def _move_cursor(self, offset_x: float, offset_y: float) -> None:
        try:
            wants_absolute = self.movement_mode_var.get() == "absolute"
            if wants_absolute and self.calibration is not None:
                self.cursor.move_to(*self.calibration.to_screen(offset_x, offset_y))
            else:
                # Relative mode, chosen explicitly or as the fallback before
                # a calibration exists for the current tracking source.
                axis = (
                    self.settings.nose
                    if self.tracking_source_var.get() == "nose"
                    else self.settings.iris
                )
                self.cursor.move(offset_x, offset_y, axis.x, axis.y)
        except pyautogui.FailSafeException:
            # User dragged the real mouse to a screen corner: pyautogui's
            # built-in panic button. Actually stop moving the cursor (not
            # just switch modes — the fallback would immediately retrigger
            # this at the same corner) until they make an open_palm gesture.
            self._gaze_paused = True
            self.gaze_status_var.set("gaze: paused (fail-safe triggered)")

    def _add_sensitivity_row(self, parent: tk.Misc, label: str, var: tk.DoubleVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text=label, width=8).pack(side="left")
        ttk.Entry(row, textvariable=var, width=8).pack(side="left")

    def _save_sensitivity(self) -> None:
        try:
            self.settings = Settings(
                iris=AxisSensitivity(x=self.iris_x_var.get(), y=self.iris_y_var.get()),
                nose=AxisSensitivity(x=self.nose_x_var.get(), y=self.nose_y_var.get()),
            )
        except tk.TclError:
            self.sensitivity_status_var.set("invalid value(s) — not saved")
            return
        save_settings(self.settings)
        self.sensitivity_status_var.set("saved")

    def _recenter_nose_tracking(self) -> None:
        self.nose_tracker.recenter()
        self.status_var.set("head position recentered")

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
