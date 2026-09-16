# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Gesture-based OS control: a webcam feed is run through MediaPipe hand tracking, classified into a
named gesture, and dispatched to an OS-level action via `pyautogui` (`default_action_map()` is
currently empty — `point`/`peace` are unbound placeholders, see GESTURES.md). A second, independent
pipeline runs MediaPipe face tracking to move the mouse cursor. Two runtime toggles in the app
window control it: **tracking source** (iris position vs. nose/head-pose position — `iris_offset`
vs `nose_offset` in gaze.py, interchangeable, same shape/sign convention) and **movement mode**
(absolute, via an in-app calibration that fits a per-user `offset -> screen pixel` mapping so gaze
maps to an absolute screen position — "look here, cursor goes here" — vs. relative/joystick-style
nudging, selectable any time regardless of calibration). `fist`/`open_palm` pause and resume gaze
cursor movement (tracking/overlay keep running either way) rather than firing an OS action, with
current state shown in its own status label. The UI is a Python desktop app (Tkinter). The
cursor-control feature is experimental and being tuned for stability.

This project was scaffolded from an empty repo; the current code is a minimal working skeleton, not
a feature-complete app.

## Commands

Setup (Windows):

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts/download_models.py
```

The last step fetches `models/hand_landmarker.task` and `models/face_landmarker.task` (not checked
into git — see `.gitignore`). `HandGestureRecognizer` and `FaceGazeTracker` each raise
`FileNotFoundError` with this same instruction if their model is missing.

Gaze cursor control also needs a one-time in-app calibration (click "Calibrate gaze" in the
running app) before it moves the cursor to an absolute position; it saves to `calibration.json`
(also gitignored) and falls back to relative movement until that file exists. Relative movement's
per-axis, per-source sensitivity (see `settings.py`) is user-tunable in the app window and
persists to `settings.json` (also gitignored) — its defaults are a starting point, not verified
against a real camera.

Run the app:

```
gesture-os
```

(equivalently: `python -m gesture_os.main`)

Run tests:

```
pytest
```

Run a single test:

```
pytest tests/test_recognizer.py::test_open_palm_has_five_extended_fingers
```

Lint:

```
ruff check .
```

Format:

```
ruff format .
```

## Architecture

Two independent pipelines share one webcam frame per tick, both wired together in
`src/gesture_os/ui/app.py` (`GestureOsApp._tick`), which is the composition root for the whole app:

```
                    +-> HandGestureRecognizer -> ActionDispatcher -> pyautogui.press
                    |        (recognizer.py)        (actions.py)
WebcamCapture -- frame
   (capture.py)     |
                    +-> FaceGazeTracker -> iris_offset/nose_offset -> CursorController -> pyautogui.moveTo/moveRel
                            (gaze.py)      (gaze.py, user-toggled       (actions.py, user-toggled absolute
                                            "tracking source")          via GazeCalibration in calibration.py,
                                                                        or relative — "movement mode")
```

- **`capture.py`** — thin wrapper around `cv2.VideoCapture`. No MediaPipe/UI dependency.
- **`recognizer.py`** — two layers, split deliberately:
  - `_extended_fingers(hand: Hand) -> list[bool]` (thumb..pinky) is pure geometry over landmark
    coordinates, with no MediaPipe dependency, so gesture-classification logic can be unit tested
    with synthetic landmark data (see `tests/test_recognizer.py`) instead of requiring a camera or
    the model at test time. `count_extended_fingers` is just `sum(_extended_fingers(hand))` — both
    single-sourced so the debug overlay below can never drift from what's actually classified.
  - `HandGestureRecognizer` wraps MediaPipe's **Tasks** `vision.HandLandmarker` (the legacy
    `mediapipe.solutions.hands` API was removed in mediapipe 1.0) in `VIDEO` running mode, feeding
    strictly increasing millisecond timestamps to `detect_for_video`. It loads
    `models/hand_landmarker.task` (see Commands above) and feeds its output through the pure function
    above. `classify()` maps an extended-finger count to a gesture name (`fist`, `point`, `peace`,
    `open_palm`, or `unknown`).
  - Gotcha: import Tasks submodules with `from mediapipe.tasks.python import vision` — writing
    `import mediapipe.tasks.python.vision as vision` raises a spurious
    `ImportError: cannot import name 'python' from 'mediapipe.tasks.python'` due to an
    attribute-resolution quirk in this MediaPipe build.
  - Gotcha: MediaPipe's handedness classifier assumes a mirrored (selfie-style) input image;
    `capture.py` feeds it a raw, unmirrored frame, so `hand.handedness` names the *opposite* of the
    true hand. Only the thumb branch in `_extended_fingers` depends on handedness (the other four
    fingers use a handedness-independent y-comparison) — it's written inverted from what you'd
    naively expect specifically to compensate for this. `test_thumb_alone_extended_for_right_hand`/
    `..._left_hand` in `tests/test_recognizer.py` pin the corrected sign; don't "fix" it back.
  - `draw_debug_overlay(frame_rgb, hand)` — same idea as gaze.py's overlay (MediaPipe has no
    built-in display): draws the hand skeleton via
    `vision.HandLandmarksConnections.HAND_CONNECTIONS`, with each fingertip colored by
    `_extended_fingers`' current read (green=extended, red=curled) — a misclassification is then
    visible per-finger, not just as a wrong final gesture name. Both this and gaze.py's function are
    named `draw_debug_overlay`; `ui/app.py` imports them aliased (`draw_hand_overlay`/
    `draw_gaze_overlay`) to avoid a collision.
- **`gaze.py`** — same two-layer split, for the face/cursor pipeline:
  - `iris_offset(face: Face) -> (x, y)` is pure geometry: iris-center position relative to each eye
    socket's own midpoint, in raw (unmirrored) image-coordinate directions, averaged over both eyes.
  - `nose_offset(face: Face) -> (x, y)` — an alternative signal, added for stability tuning: nose-tip
    position relative to the midpoint between the eyes' outer corners, normalized by inter-eye
    distance (a head-pose proxy; steadier than iris tracking, needs head movement not just a glance).
    Deliberately returns the *same shape* ([-1, 1]-ish, same sign convention) as `iris_offset` so
    either is a drop-in for `CursorController`/`GazeCalibration` — `ui/app.py`'s "Tracking source"
    toggle just picks which function to call each tick, nothing downstream needs to know which.
  - Gotcha (fixed once already, don't reintroduce it): unlike the iris — which genuinely centers on
    (0, 0) at rest because it sits within a bilaterally symmetric eye socket — the nose tip has no
    anatomical "centered" reading; it sits below eye level on *every* face, so raw `nose_offset`'s y
    is a constant positive bias at any normal pose, not a signal that crosses zero. In relative mode
    (no calibration step to absorb a constant bias into an intercept, unlike absolute mode) that
    read as "always drags the cursor down." Never feed raw `nose_offset` straight to a mover — always
    go through `NoseOffsetTracker` (below).
  - `NoseOffsetTracker` — stateful (unlike everything else in this file's pure-function layer, on
    purpose): `.read(face)` captures whatever `nose_offset` reads on its first call as `_baseline`,
    then reports `nose_offset(face) - _baseline` from then on. `.recenter()` clears the baseline so
    the next `read()` captures a fresh one — wired to `ui/app.py`'s "Recenter head position" button,
    for when the user's physical "neutral" position has changed (shifted in their seat, etc.).
  - `iris_offset`/`nose_offset` themselves are pure — no smoothing/calibration, see
    `tests/test_gaze.py`. Neither is itself a screen position — turning one into one is
    calibration.py's job.
  - `FaceGazeTracker` wraps MediaPipe's Tasks `vision.FaceLandmarker` (478-point face mesh with iris
    landmarks built in) the same way `HandGestureRecognizer` wraps `HandLandmarker` — same `VIDEO`
    running mode / monotonic timestamp pattern, same `from mediapipe.tasks.python import vision`
    import gotcha (see recognizer.py's note).
  - `draw_debug_overlay(frame_rgb, face)` — MediaPipe has no built-in display of its own (it only
    returns landmarks); this draws the eye-socket/iris points *and* the nose tip directly onto the
    frame `ui/app.py` shows — both, regardless of which tracking source is currently selected — so
    tracking quality is visible in the UI itself. Called from `GestureOsApp._tick` right after
    moving the cursor, on `frame_rgb` in place (RGB color order — it's the same array displayed).
- **`settings.py`** — persists per-source relative-movement sensitivity (`AxisSensitivity(x, y)`
  for both `iris` and `nose`, in one `Settings`) to `settings.json` at the repo root (gitignored).
  `load_settings()` returns `Settings.defaults()` if none is saved yet. Sign matters: a negative
  axis value inverts that axis' direction. The defaults negate x for the same raw-frame-mirroring
  reason as recognizer.py's handedness gotcha — "look/turn right" maps to *smaller* image x in an
  unmirrored frame — but are starting points, not verified against a real camera; that's exactly
  why they're user-editable rather than hardcoded. Calibrated absolute mode doesn't need this: its
  fitted mapping (`GazeCalibration`) self-corrects for both scale and sign from real samples.
- **`calibration.py`** — fits and persists the offset → screen-pixel mapping. Same split again:
  - `fit_calibration(samples, screen_width, screen_height) -> GazeCalibration` does per-axis linear
    least squares (`_linear_fit`, plain-Python, no numpy) over `CalibrationSample(offset,
    screen_point)` pairs. `GazeCalibration.to_screen(offset_x, offset_y)` applies it and clamps to
    the screen — both pure, see `tests/test_calibration.py`.
  - `save_calibration`/`load_calibration` persist a `GazeCalibration` as `calibration.json` at the
    repo root (gitignored). `GestureOsApp` loads it at startup; `None` means uncalibrated.
- **`ui/calibration_window.py`** — `CalibrationWindow`, a fullscreen Toplevel driven by
  `GestureOsApp`'s "Calibrate gaze" button. Walks a 5-point target list (center + 4 corners); SPACE
  captures a `CalibrationSample` using the app's current `iris_offset` reading (passed in as a
  `get_offset` callback, not a direct dependency, so this stays decoupled from `GestureOsApp`).
  Fits and saves the calibration once all 5 points are captured, then calls `on_complete`.
- **`actions.py`** — the OS-effecting layer for both pipelines:
  - `ActionDispatcher` maps a gesture name to a zero-arg callable via a plain
    `dict[str, Callable[[], None]]` (`default_action_map`). `default_action_map()` is currently
    `{}` — `point`/`peace` had volume up/down but that binding was removed and left unbound, and
    `fist`/`open_palm` are bound in `ui/app.py` instead (see below) because pausing gaze control
    needs access to app state a stateless map can't hold. Add new stateless gesture bindings here.
    `ActionDispatcher.__init__` distinguishes "no map passed" (`None`, uses `default_action_map()`)
    from "an explicitly empty map passed" (uses it as-is) — don't collapse that back to `action_map
    or default_action_map()`, which would silently ignore a caller's empty map.
  - `CursorController.move_to(x, y)` — calibrated mode, `pyautogui.moveTo` to an absolute screen
    position from `GazeCalibration.to_screen`. This is what runs once calibration.json exists.
  - `CursorController.move(offset_x, offset_y, sensitivity_x, sensitivity_y)` — relative mode,
    `pyautogui.moveRel`: `_apply_deadzone` zeroes small jitter near center on each axis
    independently, then each is scaled by its own sensitivity. The two sensitivities are passed in
    per call (not fixed at construction) since the right value differs per tracking source — caller
    (`ui/app.py`) picks `self.settings.iris` or `.nose` based on the active toggle.
- **`ui/app.py`** — `GestureOsApp` owns the Tk root window and the poll loop (`root.after`, not a
  separate thread): each tick reads one frame, runs it through both the hand recognizer (dispatching
  any resulting gesture, then `draw_hand_overlay`) and the face gaze tracker (moving the cursor via
  calibrated or fallback mode, tracked in `self.calibration`, then `draw_gaze_overlay`), and redraws
  the frame in the video `Label`.
  - `self.tracking_source_var` (`tk.StringVar`, "iris"/"nose") — read fresh each tick in `_tick` to
    pick `iris_offset(face)` or `self.nose_tracker.read(face)` (never raw `nose_offset` directly —
    see the gotcha in gaze.py's entry above); nothing is cached, so flipping the radio button takes
    effect on the very next frame. `self.nose_tracker` (a `NoseOffsetTracker`) persists across mode
    switches — switching away from and back to nose tracking keeps the same baseline, since the
    user's physical position presumably hasn't changed just because they toggled a radio button.
    `_recenter_nose_tracking` (the "Recenter head position" button) resets it explicitly.
  - `self.movement_mode_var` (`tk.StringVar`, "absolute"/"relative") — read fresh each call in
    `_move_cursor`; "absolute" still falls back to relative when `self.calibration is None`, so the
    two toggles are fully independent (any tracking source × either movement mode is a valid
    combination, calibration permitting). In relative mode, `_move_cursor` also re-reads
    `self.tracking_source_var` to pick `self.settings.iris` vs `.nose` for `CursorController.move`.
  - `self.settings` (a `settings.Settings`, loaded at startup) backs four `tk.DoubleVar`s (Iris/Nose
    × X/Y) in the "Relative movement sensitivity" panel. They're edited freely and only take effect
    on "Save sensitivity" (`_save_sensitivity`), which rebuilds `self.settings` from the vars and
    calls `settings.save_settings` — a `tk.TclError` from a non-numeric entry is caught and reported
    in `sensitivity_status_var` rather than crashing or silently keeping stale values.
  - `self._gaze_paused` gates cursor movement only — tracking and both debug overlays keep
    running, and other gestures still dispatch, while paused. `__init__` overrides
    `default_action_map()`'s result with `action_map["fist"] = self._pause_gaze_control` /
    `action_map["open_palm"] = self._resume_gaze_control` before constructing `ActionDispatcher`,
    since those two closures need `self`.
  - `self.gaze_status_var` is a *separate* `StringVar` from `self.status_var` specifically so the
    gaze pause/resume/fail-safe state is never overwritten by the generic "last gesture"/"running"/
    "calibrated" messages on `status_var`.
  - `pyautogui.FailSafeException` (the user dragging the real mouse to a screen corner — pyautogui's
    built-in panic button) is caught in `_move_cursor` and sets `self._gaze_paused = True` — the
    same state a `fist` gesture sets, resumed the same way (`open_palm`). Earlier this only cleared
    `self.calibration`, which didn't actually stop movement (the uncalibrated fallback would keep
    trying to move the cursor and could immediately retrigger the fail-safe at the same corner).

When adding a new gesture: extend `count_extended_fingers`'s output mapping in
`HandGestureRecognizer.classify`, then bind it in `actions.default_action_map` (stateless) or
`GestureOsApp.__init__`'s `action_map` overrides (needs app state). Keep new classification logic
in the pure-function layer so it stays unit-testable without a camera.
