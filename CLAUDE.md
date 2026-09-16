# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Gesture-based OS control: a webcam feed is run through MediaPipe hand tracking, classified into a
named gesture, and dispatched to an action (`default_action_map()` in actions.py is stateless and
currently empty — `point` is unbound; `fist`/`open_palm`/`peace` are bound with app-state closures
in `ui/app.py` instead, see GESTURES.md and the "Show gesture guide" button in the app itself). A
second, independent pipeline runs MediaPipe face tracking to move the mouse cursor. Two runtime
toggles in the app
window control it: **tracking source** (iris position vs. nose/head-pose position — `iris_offset`
vs `nose_offset` in gaze.py, interchangeable, same shape/sign convention) and **movement mode**
(absolute, via an in-app calibration that fits a per-user `offset -> screen pixel` mapping so gaze
maps to an absolute screen position — "look here, cursor goes here" — vs. relative/joystick-style
nudging, selectable any time regardless of calibration). A large "Mouse Control: ON/OFF" button and
`fist`/`open_palm` both pause/resume gaze cursor movement — same single state either way, not two
switches (tracking/overlay keep running either way) — with current state shown in its own status
label and the button's own text/color. A third, independent face-tracking feature — winking one
eye alone (not blinking both) fires a left/right click via MediaPipe's `eyeBlinkLeft`/
`eyeBlinkRight` blendshapes — runs regardless of the two toggles above, also suppressed while
mouse control is off. "Save settings" persists both toggles, per-source sensitivity, the nose
deadzone, the wink threshold, and the tick-loop poll interval to `settings.json`, restored at
startup. The UI is a Python desktop app (Tkinter). The cursor-control feature is experimental and
being tuned for stability and smoothness — `pyautogui.PAUSE`'s 0.1s-per-call default was found
capping cursor updates to 10/sec regardless of anything else in the app; see actions.py.

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
    import gotcha (see recognizer.py's note). Constructed with `output_face_blendshapes=True`, so
    `process()` also populates `Face.blendshapes` — a `dict[str, float]` of MediaPipe's 52 named
    ARKit-style facial-expression scores (0-1 each), extracted from `result.face_blendshapes[0]`.
    This is a model output, not geometry this code computes from `landmarks`.
  - `eye_blink_scores(face) -> (left, right)` reads `face.blendshapes["eyeBlinkLeft"/"eyeBlinkRight"]`
    (0.0 if blendshapes weren't populated). `detect_wink(face, threshold) -> "left"/"right"/None`
    is true only when *one* eye is closed past `threshold` and the other isn't — both eyes closing
    together is an ordinary blink and must NOT count, so it deliberately returns `None` for that
    case too, same as both-open. Verified against a real photo (not just synthetic landmark data):
    open eyes measured ~0.27 on this scale — see the default `wink_threshold` in settings.py.
  - `WinkClickDetector` — stateful like `NoseOffsetTracker`, for the same reason: `detect_wink` is
    level-triggered (true every frame the eye stays shut), but a click must fire once per wink, not
    once per frame — `.update(face, threshold)` returns the eye label only on the open→closed
    transition, `None` while held or open. Feed it every frame regardless of app pause state so its
    edge-tracking stays accurate; only the *dispatch* of the resulting click should be suppressed
    when paused (see `ui/app.py`'s `_tick`) — don't gate the `.update()` call itself.
  - `draw_debug_overlay(frame_rgb, face)` — MediaPipe has no built-in display of its own (it only
    returns landmarks); this draws the eye-socket/iris points *and* the nose tip directly onto the
    frame `ui/app.py` shows — both, regardless of which tracking source is currently selected — so
    tracking quality is visible in the UI itself. Called from `GestureOsApp._tick` right after
    moving the cursor, on `frame_rgb` in place (RGB color order — it's the same array displayed).
- **`settings.py`** — persists the user's cursor-control preferences to `settings.json` at the repo
  root (gitignored): per-source relative-movement sensitivity (`AxisSensitivity(x, y)` for both
  `iris` and `nose`), `nose_deadzone_x`/`nose_deadzone_y` (independent per axis, nose-only for now
  — iris has no sliders yet, see actions.py's bullet), `wink_threshold` (see gaze.py's
  `detect_wink` bullet), `tracking_source`/`movement_mode` (the two `ui/app.py` radio-button
  states), and `poll_ms` (the tick-loop interval — see its own field docstring for what it
  actually controls) so a session resumes exactly where it left off.
  `load_settings()` returns `Settings.defaults()` if none is saved yet, and fills in any of these
  with defaults via `.get()` if loading an older settings.json saved before that field existed —
  don't replace that with direct key access, it'll raise `KeyError` on such a file (there's a real
  one from before this feature that this was written against). The X/Y split itself has its own
  migration: an older file's single shared `"nose_deadzone"` key becomes the fallback for *both*
  `nose_deadzone_x` and `nose_deadzone_y` (not the newer, possibly different, default for each) —
  see `test_load_settings_migrates_an_old_single_nose_deadzone_to_both_axes`. Sign matters on
  sensitivity: a
  negative axis value inverts that axis' direction. The sensitivity defaults negate x for the same
  raw-frame-mirroring reason as recognizer.py's handedness gotcha — "look/turn right" maps to
  *smaller* image x in an unmirrored frame — but are starting points, not verified against a real
  camera; that's exactly why they're user-editable rather than hardcoded. Calibrated absolute mode
  doesn't need the sensitivity values: its fitted mapping (`GazeCalibration`) self-corrects for
  both scale and sign from real samples.
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
  - Sets `pyautogui.PAUSE = 0` at module import. pyautogui's default (0.1s slept after *every*
    call, meant for scripted automation you can visually track) was capping `CursorController`'s
    real-time, once-per-frame cursor updates to 10/sec regardless of anything else in the app —
    measured as the dominant bottleneck for cursor smoothness, well beyond `ui/app.py`'s tick
    interval. `FAILSAFE` is left at its default (on) — that's the panic-button escape hatch, not
    a per-call throttle, so there's no tension between removing PAUSE and keeping it.
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
  - `CursorController.move(offset_x, offset_y, sensitivity_x, sensitivity_y, deadzone_x=0.15,
    deadzone_y=0.15)` — relative mode, `pyautogui.moveRel`: `_apply_deadzone` zeroes small jitter
    near center on each axis independently using that axis's own deadzone, then each is scaled by
    its own sensitivity. All four are passed in per call (nothing fixed on the instance —
    `CursorController` holds no state at all) since the right values differ per tracking source —
    caller (`ui/app.py`) picks `self.settings.iris` or `.nose` for sensitivity, and for nose
    specifically also passes `self.nose_deadzone_x_var.get()`/`.nose_deadzone_y_var.get()` as
    `deadzone_x`/`deadzone_y` (iris calls without them, falling back to the `0.15` defaults — no
    iris sliders yet).
  - `click(button="left")` — a thin `pyautogui.click` wrapper for wink-to-click
    (`gaze.WinkClickDetector`), which already debounces to one call per wink; `click` itself does
    no debouncing of its own.
- **`ui/app.py`** — `GestureOsApp` owns the Tk root window and the poll loop (`root.after`, not a
  separate thread): each tick reads one frame, runs it through the hand recognizer (dispatching any
  resulting gesture, then `draw_hand_overlay`), the face gaze tracker (moving the cursor via
  calibrated or fallback mode, tracked in `self.calibration`, then `draw_gaze_overlay`), and the
  wink-click detector, then redraws the frame in the video `Label`.
  - Wink-click wiring in `_tick`: `self.wink_click_detector.update(face, self.wink_threshold_var.get())`
    is called whenever a face is present, *unconditionally* — even while `self._gaze_paused` — so
    its edge-tracking stays accurate; only the resulting `click(eye)` call is gated on
    `not self._gaze_paused`. Don't move the `.update()` call inside that gate — winking during a
    pause would otherwise be missed/misfire once resumed (see gaze.py's `WinkClickDetector` bullet).
  - `self._poll_ms()` reads `self.poll_ms_var` (the "Tick interval (ms)" field) live for
    `root.after`'s delay each tick, clamped to `>= 0`, falling back to `_DEFAULT_POLL_MS` on a
    `tk.TclError` from a non-numeric entry. Not a fixed-rate timer: it's the *minimum* delay after
    a tick finishes before the next is scheduled, so it only matters once a tick's own work
    (capture + two MediaPipe inferences + drawing, ~10ms measured for inference alone on a blank
    frame) is faster than it — lowering it below that floor does nothing further.
  - `_record_tick_rate()`, called first thing in `_tick`, measures real wall-clock time since the
    previous call (`time.perf_counter()` deltas — the whole loop's actual period, not just the
    "Tick interval" setting) and shows it smoothed (module-level `_ema`, a plain exponential moving
    average — pure, tested in `tests/test_app.py`) in `self.tick_rate_var`. This exists so "movement
    feels slower" is checkable against a real number instead of only impression; measuring the
    *actual* period this way, rather than trusting the configured interval, is also how you'd tell
    whether a reported slowdown is this app's own bottleneck or external (CPU load, camera driver,
    thermal throttling). `start()` resets `_last_tick_at`/`_tick_ms_ema` to `None` so a stop/start
    gap is never counted as one enormous tick; `stop()` resets the *displayed* text immediately but
    leaves those two alone (the next `start()` is what actually needs to reset them).
  - `self.tracking_source_var` (`tk.StringVar`, "iris"/"nose") — read fresh each tick in `_tick` to
    pick `iris_offset(face)` or `self.nose_tracker.read(face)` (never raw `nose_offset` directly —
    see the gotcha in gaze.py's entry above); nothing is cached, so flipping the radio button takes
    effect on the very next frame. `self.nose_tracker` (a `NoseOffsetTracker`) persists across mode
    switches — switching away from and back to nose tracking keeps the same baseline, since the
    user's physical position presumably hasn't changed just because they toggled a radio button.
    `_recenter_nose_tracking` resets it explicitly — wired to both the "Recenter head position"
    button and `action_map["peace"]` (set alongside `action_map["fist"]`/`["open_palm"]` in
    `__init__`, same reasoning: needs `self`, so it can't live in the stateless
    `actions.default_action_map()`).
  - `self.movement_mode_var` (`tk.StringVar`, "absolute"/"relative") — read fresh each call in
    `_move_cursor`; "absolute" still falls back to relative when `self.calibration is None`, so the
    two toggles are fully independent (any tracking source × either movement mode is a valid
    combination, calibration permitting). In relative mode, `_move_cursor` also re-reads
    `self.tracking_source_var` to pick `self.settings.iris` vs `.nose` for `CursorController.move`.
  - `self.settings` (a `settings.Settings`, loaded at startup) backs four `tk.DoubleVar`s (Iris/Nose
    × X/Y) in the "Relative movement sensitivity" panel, `self.nose_deadzone_x_var`/
    `self.nose_deadzone_y_var` and `self.wink_threshold_var` (all `tk.DoubleVar`, all sliders),
    `self.poll_ms_var` (an `tk.IntVar`) in the "Performance" panel, and seeds
    `tracking_source_var`/`movement_mode_var`'s *initial* value (their live value is whatever the
    radio buttons currently show, read fresh every tick — see above). All of it is edited freely at
    runtime and only persisted on "Save settings" (`_save_settings`), which rebuilds
    `self.settings` from the current var values (sensitivity fields, both nose deadzones, wink
    threshold, both radio-button choices, and poll interval) and calls `settings.save_settings` —
    a `tk.TclError` from a non-numeric entry is caught and reported in `settings_status_var` rather
    than crashing or silently keeping stale values. The three slider vars are driven by `ttk.Scale`
    widgets (not free-text `ttk.Entry` like the sensitivity rows) so they can't hold invalid text
    in the first place — no equivalent `try`/`except` guards reading them elsewhere (e.g. in
    `_move_cursor`/`_tick`). `_add_slider(parent, label, initial, to=0.5) -> (value_var, label_var)`
    is the shared helper that builds one such slider row plus its live-updating numeric label
    (`ttk.Scale` doesn't show its own value); the nose deadzones use the default 0-0.5 range, the
    wink threshold passes `to=1.0` since a blendshape score's full range is 0-1.
  - `self.iris_sensitivity_frame`/`self.nose_sensitivity_frame` hold the Iris X/Y and Nose X/Y
    entry rows respectively (the latter also has both nose deadzone sliders), both children of the
    same `sensitivity_frame`, but only one is ever
    `pack()`ed at a time (the other `pack_forget()`) — `_update_sensitivity_visibility` picks based
    on `tracking_source_var`, wired via `tracking_source_var.trace_add("write", ...)` so it reacts
    to the radio button itself, not just the once-a-tick `_tick` read. Called once manually right
    after creating both frames, to set the correct initial visibility before any trace fires.
  - `self._gaze_paused` — the one on/off state for cursor movement, set at the very top of
    `__init__` (before any widget reads it). Tracking and both debug overlays keep running, and
    other gestures still dispatch, while paused. Three independent triggers all funnel through the
    same two methods, `_pause_gaze_control(reason=...)`/`_resume_gaze_control(reason=...)`, so there
    is exactly one source of truth rather than parallel state to keep in sync:
    - `fist`/`open_palm` gestures — `__init__` overrides `default_action_map()`'s result with
      `action_map["fist"] = self._pause_gaze_control` / `action_map["open_palm"] =
      self._resume_gaze_control` before constructing `ActionDispatcher` (default `reason` text),
      since those two closures need `self`.
    - The large `self.mouse_control_button` (a plain `tk.Button`, not `ttk.Button`, since `ttk`
      doesn't support `font`/`bg` directly and this one is meant to be visually prominent) —
      `_toggle_mouse_control` calls whichever of the pair applies with `reason="button"`.
    - `pyautogui.FailSafeException` (dragging the real mouse to a screen corner — pyautogui's
      built-in panic button), caught in `_move_cursor`, calls `_pause_gaze_control(reason="fail-safe
      triggered")`. Earlier this only cleared `self.calibration`, which didn't actually stop
      movement (the uncalibrated fallback would keep trying to move the cursor and could
      immediately retrigger the fail-safe at the same corner).
    Both methods end by calling `_update_mouse_control_button()`, so the button's label/color and
    `self.gaze_status_var`'s text stay in sync no matter which of the three triggered the change.
  - `self.gaze_status_var` is a *separate* `StringVar` from `self.status_var` specifically so the
    gaze pause/resume/fail-safe state is never overwritten by the generic "last gesture"/"running"/
    "calibrated" messages on `status_var`.
  - `_show_gesture_guide()` (the "Show gesture guide" button) — a `tk.Toplevel` listing
    `_GESTURE_GUIDE`, a module-level `list[tuple[str, str]]` near the top of the file. This is a
    **hand-maintained lookup table, not a live introspection** of `action_map`/`default_action_map`/
    `WinkClickDetector` — there's no generic way to turn an arbitrary bound closure back into a
    human description, so whoever changes a binding has to update this table too, or the guide
    silently drifts from what the app actually does. `self._gesture_guide_window` tracks the open
    window so a second click brings the existing one to front (`winfo_exists()` check) instead of
    stacking duplicates; `None`/a destroyed window both correctly fall through to opening a fresh one.

When adding a new gesture: extend `count_extended_fingers`'s output mapping in
`HandGestureRecognizer.classify`, then bind it in `actions.default_action_map` (stateless) or
`GestureOsApp.__init__`'s `action_map` overrides (needs app state). Keep new classification logic
in the pure-function layer so it stays unit-testable without a camera. Update `_GESTURE_GUIDE` too
— it won't update itself.
