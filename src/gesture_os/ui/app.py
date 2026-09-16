"""Tkinter desktop UI: shows the webcam feed and drives both input pipelines
(hand gestures and gaze-based cursor movement) from it.

This is the composition root — it is the only module that wires capture,
the recognizer/dispatcher pair, and the gaze tracker/cursor pair together
into one running loop.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

import cv2
import pyautogui
from PIL import Image, ImageTk

from gesture_os.actions import ActionDispatcher, CursorController, click, default_action_map
from gesture_os.calibration import GazeCalibration, load_calibration
from gesture_os.capture import WebcamCapture
from gesture_os.gaze import FaceGazeTracker, NoseOffsetTracker, WinkClickDetector, iris_offset
from gesture_os.gaze import draw_debug_overlay as draw_gaze_overlay
from gesture_os.recognizer import HandGestureRecognizer
from gesture_os.recognizer import draw_debug_overlay as draw_hand_overlay
from gesture_os.settings import AxisSensitivity, Settings, load_settings, save_settings
from gesture_os.ui.calibration_window import CalibrationWindow

# Fallback used only if the "Tick interval" field holds something unusable
# (blank, negative, non-numeric) — the real, user-adjustable value lives in
# settings.poll_ms / self.poll_ms_var, not here.
_DEFAULT_POLL_MS = 1

# Smoothing factor for the live tick-rate readout: how much weight the
# newest sample gets. Low enough that one stray slow/fast tick (e.g. the
# OS briefly scheduling something else) doesn't make the displayed number
# jump around, high enough that a real, sustained change in tick rate
# still shows up within roughly a second.
_TICK_RATE_EMA_ALPHA = 0.1


def _ema(previous: float | None, sample: float, alpha: float = _TICK_RATE_EMA_ALPHA) -> float:
    """Exponential moving average: `previous` seeded with the first sample."""
    return sample if previous is None else alpha * sample + (1 - alpha) * previous


# What each gesture currently does — shown verbatim in the "Gesture guide"
# popup (_show_gesture_guide). Kept as one small, easy-to-scan table right
# next to the actual bindings below (action_map[...] assignments in
# __init__, default_action_map() in actions.py, WinkClickDetector in
# gaze.py) specifically so it's easy to keep in sync when those change —
# there's no runtime introspection tying this to the real dispatch tables,
# so a changed binding needs this table updated by hand too.
_GESTURE_GUIDE: list[tuple[str, str]] = [
    ("Fist", "Pause gaze cursor movement"),
    ("Point (index finger)", "(unbound)"),
    ("Peace sign", "Recenter head / nose tracking"),
    ("Open palm", "Resume gaze cursor movement"),
    ("Wink — left eye", "Left click"),
    ("Wink — right eye", "Right click"),
    ("Blink — both eyes", "No action (an ordinary blink, not a wink)"),
]


class GestureOsApp:
    """Owns the Tk root window and the capture/recognize/act loop."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("gesture_os")

        # Set before any widget that reads it, so the big button below can
        # show the right label/color from its very first paint.
        self._gaze_paused = False

        self.mouse_control_button = tk.Button(
            self.root,
            font=("Segoe UI", 14, "bold"),
            height=2,
            fg="white",
            command=self._toggle_mouse_control,
        )
        self.mouse_control_button.pack(fill="x", padx=4, pady=6)
        self._update_mouse_control_button()

        self._gesture_guide_window: tk.Toplevel | None = None
        ttk.Button(
            self.root, text="Show gesture guide", command=self._show_gesture_guide
        ).pack(fill="x", padx=4)

        self.video_label = ttk.Label(self.root)
        self.video_label.pack()

        self.status_var = tk.StringVar(value="stopped")
        ttk.Label(self.root, textvariable=self.status_var).pack()
        self.gaze_status_var = tk.StringVar(value="gaze: active")
        ttk.Label(self.root, textvariable=self.gaze_status_var).pack()
        ttk.Button(self.root, text="Calibrate gaze", command=self._start_calibration).pack()

        self.settings = load_settings()

        self.tracking_source_var = tk.StringVar(value=self.settings.tracking_source)
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

        self.movement_mode_var = tk.StringVar(value=self.settings.movement_mode)
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

        self.iris_x_var = tk.DoubleVar(value=self.settings.iris.x)
        self.iris_y_var = tk.DoubleVar(value=self.settings.iris.y)
        self.nose_x_var = tk.DoubleVar(value=self.settings.nose.x)
        self.nose_y_var = tk.DoubleVar(value=self.settings.nose.y)
        sensitivity_frame = ttk.LabelFrame(self.root, text="Relative movement sensitivity")
        sensitivity_frame.pack(fill="x", padx=4, pady=2)
        # Only one of these two is ever packed at a time — see
        # _update_sensitivity_visibility — so only the active tracking
        # source's sensitivity fields are shown.
        self.iris_sensitivity_frame = ttk.Frame(sensitivity_frame)
        self._add_sensitivity_row(self.iris_sensitivity_frame, "Iris X", self.iris_x_var)
        self._add_sensitivity_row(self.iris_sensitivity_frame, "Iris Y", self.iris_y_var)
        self.nose_sensitivity_frame = ttk.Frame(sensitivity_frame)
        self._add_sensitivity_row(self.nose_sensitivity_frame, "Nose X", self.nose_x_var)
        self._add_sensitivity_row(self.nose_sensitivity_frame, "Nose Y", self.nose_y_var)
        self.nose_deadzone_x_var, self.nose_deadzone_x_label_var = self._add_slider(
            self.nose_sensitivity_frame, "Nose deadzone X", self.settings.nose_deadzone_x
        )
        self.nose_deadzone_y_var, self.nose_deadzone_y_label_var = self._add_slider(
            self.nose_sensitivity_frame, "Nose deadzone Y", self.settings.nose_deadzone_y
        )
        self.tracking_source_var.trace_add("write", self._update_sensitivity_visibility)
        self._update_sensitivity_visibility()

        self.wink_click_detector = WinkClickDetector()
        wink_frame = ttk.LabelFrame(self.root, text="Wink to click")
        wink_frame.pack(fill="x", padx=4, pady=2)
        self.wink_threshold_var, self.wink_threshold_label_var = self._add_slider(
            wink_frame, "Wink threshold", self.settings.wink_threshold, to=1.0
        )

        self.poll_ms_var = tk.IntVar(value=self.settings.poll_ms)
        performance_frame = ttk.LabelFrame(self.root, text="Performance")
        performance_frame.pack(fill="x", padx=4, pady=2)
        interval_row = ttk.Frame(performance_frame)
        interval_row.pack(fill="x")
        ttk.Label(interval_row, text="Tick interval (ms)", width=16).pack(side="left")
        ttk.Entry(interval_row, textvariable=self.poll_ms_var, width=8).pack(side="left")
        ttk.Label(
            interval_row, text="lower = smoother, more CPU; 0-2 is usually plenty"
        ).pack(side="left")
        rate_row = ttk.Frame(performance_frame)
        rate_row.pack(fill="x")
        ttk.Label(rate_row, text="Actual tick rate", width=16).pack(side="left")
        self.tick_rate_var = tk.StringVar(value="(warming up...)")
        ttk.Label(rate_row, textvariable=self.tick_rate_var).pack(side="left")
        self._last_tick_at: float | None = None
        self._tick_ms_ema: float | None = None

        save_frame = ttk.Frame(self.root)
        save_frame.pack(fill="x", padx=4, pady=2)
        self.settings_status_var = tk.StringVar(value="")
        ttk.Button(save_frame, text="Save settings", command=self._save_settings).pack(
            side="left"
        )
        ttk.Label(save_frame, textvariable=self.settings_status_var).pack(side="left")

        self.capture = WebcamCapture()
        self.recognizer = HandGestureRecognizer()
        action_map = default_action_map()
        action_map["fist"] = self._pause_gaze_control
        action_map["open_palm"] = self._resume_gaze_control
        action_map["peace"] = self._recenter_nose_tracking
        self.dispatcher = ActionDispatcher(action_map)
        self.gaze_tracker = FaceGazeTracker()
        self.cursor = CursorController()
        self.calibration: GazeCalibration | None = load_calibration()
        self._last_offset: tuple[float, float] | None = None
        self._running = False

    def start(self) -> None:
        self.capture.open()
        self._running = True
        self.status_var.set("running")
        # Reset so a stop/start gap isn't counted as one giant "tick" that
        # would otherwise spike the EMA in _record_tick_rate.
        self._last_tick_at = None
        self._tick_ms_ema = None
        self._tick()

    def stop(self) -> None:
        self._running = False
        self.capture.close()
        self.status_var.set("stopped")
        self.tick_rate_var.set("(warming up...)")

    def _tick(self) -> None:
        if not self._running:
            return
        self._record_tick_rate()
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

            if face is not None:
                # Always fed, even while paused, so the detector's edge
                # state (which eye is currently held closed) stays in sync
                # with reality — only the resulting click is suppressed.
                winking_eye = self.wink_click_detector.update(face, self.wink_threshold_var.get())
                if winking_eye is not None and not self._gaze_paused:
                    click(winking_eye)
                    self.status_var.set(f"running - click ({winking_eye} eye)")

            image = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
            self.video_label.configure(image=image)
            self.video_label.image = image  # keep a reference alive
        self.root.after(self._poll_ms(), self._tick)

    def _record_tick_rate(self) -> None:
        """Measures real wall-clock time between successive `_tick` calls
        (capture + both MediaPipe inferences + drawing + the `after` delay
        itself — the whole loop, not just one part of it) and shows a
        smoothed rate, so "movement feels slower" is something you can
        actually check against a number instead of only impression."""
        now = time.perf_counter()
        if self._last_tick_at is not None:
            elapsed_ms = (now - self._last_tick_at) * 1000
            self._tick_ms_ema = _ema(self._tick_ms_ema, elapsed_ms)
            fps = 1000 / self._tick_ms_ema if self._tick_ms_ema > 0 else 0.0
            self.tick_rate_var.set(f"{self._tick_ms_ema:.1f} ms/tick (~{fps:.0f} fps)")
        self._last_tick_at = now

    def _poll_ms(self) -> int:
        """The current tick interval, read live so the "Tick interval"
        field takes effect immediately — not just after "Save settings".
        Not a fixed-rate timer: if a tick's own work (camera read + two
        MediaPipe inferences + drawing) takes longer than this, that's the
        real limit, not this number."""
        try:
            return max(0, self.poll_ms_var.get())
        except tk.TclError:
            return _DEFAULT_POLL_MS

    def _move_cursor(self, offset_x: float, offset_y: float) -> None:
        try:
            wants_absolute = self.movement_mode_var.get() == "absolute"
            if wants_absolute and self.calibration is not None:
                self.cursor.move_to(*self.calibration.to_screen(offset_x, offset_y))
            else:
                # Relative mode, chosen explicitly or as the fallback before
                # a calibration exists for the current tracking source.
                if self.tracking_source_var.get() == "nose":
                    axis = self.settings.nose
                    self.cursor.move(
                        offset_x,
                        offset_y,
                        axis.x,
                        axis.y,
                        deadzone_x=self.nose_deadzone_x_var.get(),
                        deadzone_y=self.nose_deadzone_y_var.get(),
                    )
                else:
                    axis = self.settings.iris
                    self.cursor.move(offset_x, offset_y, axis.x, axis.y)
        except pyautogui.FailSafeException:
            # User dragged the real mouse to a screen corner: pyautogui's
            # built-in panic button. Actually stop moving the cursor (not
            # just switch modes — the fallback would immediately retrigger
            # this at the same corner) until they turn it back on.
            self._pause_gaze_control(reason="fail-safe triggered")

    def _add_sensitivity_row(self, parent: tk.Misc, label: str, var: tk.DoubleVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text=label, width=8).pack(side="left")
        ttk.Entry(row, textvariable=var, width=8).pack(side="left")

    def _add_slider(
        self, parent: tk.Misc, label: str, initial: float, to: float = 0.5
    ) -> tuple[tk.DoubleVar, tk.StringVar]:
        """A slider (not a free-text field — a slider can't hold invalid
        text, unlike the sensitivity rows) for a 0-`to` value. Returns the
        value var and a live-updating label var, since ttk.Scale doesn't
        show its own numeric value."""
        value_var = tk.DoubleVar(value=initial)
        label_var = tk.StringVar(value=f"{initial:.2f}")
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text=label, width=14).pack(side="left")
        ttk.Scale(
            row,
            from_=0.0,
            to=to,
            orient="horizontal",
            variable=value_var,
            command=lambda value: label_var.set(f"{float(value):.2f}"),
            length=140,
        ).pack(side="left")
        ttk.Label(row, textvariable=label_var, width=5).pack(side="left")
        return value_var, label_var

    def _update_sensitivity_visibility(self, *_tk_trace_args: object) -> None:
        """Shows only the sensitivity fields for the currently selected
        tracking source. `*_tk_trace_args` absorbs the (name, index, mode)
        arguments tkinter's variable trace passes, which this doesn't need."""
        if self.tracking_source_var.get() == "nose":
            self.iris_sensitivity_frame.pack_forget()
            self.nose_sensitivity_frame.pack(fill="x")
        else:
            self.nose_sensitivity_frame.pack_forget()
            self.iris_sensitivity_frame.pack(fill="x")

    def _save_settings(self) -> None:
        """Saves everything the user can currently adjust: per-source
        sensitivity, tracking source, movement mode, tick interval, nose
        deadzone (X and Y independently), and wink-click threshold — so a
        session picks up exactly where it left off next run."""
        try:
            self.settings = Settings(
                iris=AxisSensitivity(x=self.iris_x_var.get(), y=self.iris_y_var.get()),
                nose=AxisSensitivity(x=self.nose_x_var.get(), y=self.nose_y_var.get()),
                tracking_source=self.tracking_source_var.get(),
                movement_mode=self.movement_mode_var.get(),
                poll_ms=self.poll_ms_var.get(),
                nose_deadzone_x=self.nose_deadzone_x_var.get(),
                nose_deadzone_y=self.nose_deadzone_y_var.get(),
                wink_threshold=self.wink_threshold_var.get(),
            )
        except tk.TclError:
            self.settings_status_var.set("invalid value(s) — not saved")
            return
        save_settings(self.settings)
        self.settings_status_var.set("saved")

    def _recenter_nose_tracking(self) -> None:
        self.nose_tracker.recenter()
        self.status_var.set("head position recentered")

    def _toggle_mouse_control(self) -> None:
        if self._gaze_paused:
            self._resume_gaze_control(reason="button")
        else:
            self._pause_gaze_control(reason="button")

    def _update_mouse_control_button(self) -> None:
        if self._gaze_paused:
            text, color = "Mouse Control: OFF  (click to turn on)", "#a83232"
        else:
            text, color = "Mouse Control: ON  (click to turn off)", "#2e7d32"
        self.mouse_control_button.configure(text=text, bg=color)

    def _pause_gaze_control(self, reason: str = "fist") -> None:
        self._gaze_paused = True
        self.gaze_status_var.set(f"gaze: paused ({reason})")
        self._update_mouse_control_button()

    def _resume_gaze_control(self, reason: str = "open palm") -> None:
        self._gaze_paused = False
        self.gaze_status_var.set(f"gaze: active ({reason})")
        self._update_mouse_control_button()

    def _show_gesture_guide(self) -> None:
        """Opens the gesture-to-action reference (see `_GESTURE_GUIDE`), or
        brings the existing one to front instead of opening a duplicate."""
        if self._gesture_guide_window is not None and self._gesture_guide_window.winfo_exists():
            self._gesture_guide_window.lift()
            self._gesture_guide_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("Gesture guide")
        window.resizable(False, False)
        for row, (gesture, action) in enumerate(_GESTURE_GUIDE):
            ttk.Label(window, text=gesture, font=("Segoe UI", 10, "bold")).grid(
                row=row, column=0, sticky="w", padx=(10, 20), pady=4
            )
            ttk.Label(window, text=action).grid(row=row, column=1, sticky="w", padx=(0, 10), pady=4)
        self._gesture_guide_window = window

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
