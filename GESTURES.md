# Gesture Mappings

Default bindings from `default_action_map()` in [src/gesture_os/actions.py](src/gesture_os/actions.py),
plus two bound directly in [src/gesture_os/ui/app.py](src/gesture_os/ui/app.py) since they control
app state rather than firing a stateless OS action. Gestures are classified in
[src/gesture_os/recognizer.py](src/gesture_os/recognizer.py) by the number of extended fingers on
one hand.

| Gesture      | Hand shape                        | Extended fingers | Action                |
| ------------ | ---------------------------------- | :---------------: | --------------------- |
| `fist`       | closed hand                        | 0                  | **Pause** gaze cursor |
| `point`      | index finger only                  | 1                  | *(unbound)*           |
| `peace`      | index + middle finger               | 2                  | *(unbound)*           |
| `open_palm`  | all five fingers extended          | 5                  | **Resume** gaze cursor|
| `unknown`    | any other count (3 or 4 fingers)   | 3, 4               | No action              |

`point`/`peace` previously triggered volume up/down; that binding was removed and left empty for
now — see "Adding or changing a binding" below to rebind them.

Pausing/resuming only stops cursor *movement* — the video feed, iris tracking, and its debug
overlay keep running the whole time, and fist/peace/point still fire while paused. Current state
shows in its own "gaze: active/paused" label in the app window (see Cursor movement below), kept
separate from the general status line so it's never overwritten by other status messages.

The large **Mouse Control: ON/OFF** button at the top of the app window does the exact same
pause/resume as `fist`/`open_palm` — it's a second way to reach the same on/off state (for when
gesturing isn't convenient), not a separate switch. Whichever one you use last — gesture or
button — is reflected in both: the button's label/color and the "gaze:" status line always agree.

## Adding or changing a binding

1. Extend the finger-count → gesture name mapping in `HandGestureRecognizer.classify`
   (`src/gesture_os/recognizer.py`) if you're introducing a new gesture.
2. For a stateless OS action, bind the gesture name to a `pyautogui` call in `default_action_map()`
   (`src/gesture_os/actions.py`). For one that needs app state (like pause/resume), bind it instead
   in `GestureOsApp.__init__` (`src/gesture_os/ui/app.py`), overriding `default_action_map()`'s
   result before constructing `ActionDispatcher`.

Keep any new gesture-detection logic in the pure-function layer (alongside
`count_extended_fingers`) so it stays unit-testable without a camera — see
`tests/test_recognizer.py`.

## Hand tracking overlay

Like the gaze overlay below, `recognizer.py`'s `draw_debug_overlay` draws exactly what's being
tracked onto the live video feed in the app window: gray lines/dots for the whole hand skeleton, a
**green** dot on each fingertip currently read as extended, **red** on each read as curled — the
exact per-finger signal `count_extended_fingers` sums to classify the gesture. If a gesture is
misread, this shows which specific finger MediaPipe/the geometry got wrong, rather than only the
final gesture name. (`ui/app.py` imports it as `draw_hand_overlay`, since `gaze.py` has a function
of the same name for iris tracking — see below.)

## Cursor movement (gaze, experimental)

Separately from hand gestures, [src/gesture_os/gaze.py](src/gesture_os/gaze.py) moves the mouse
cursor from face tracking. The app window has two independent toggles for this:

**Tracking source** — which signal drives the cursor:

- **Iris** (default) — `iris_offset`: iris position within each eye socket, averaged over both
  eyes. Follows just your eyes, but is the noisier of the two signals.
- **Face / nose** — nose-tip position relative to the midpoint between your eyes, normalized by
  inter-eye distance (so it stays roughly constant as you move closer to/farther from the camera)
  — a head-pose proxy. Steadier than iris tracking, at the cost of needing to move your head, not
  just glance, to move the cursor. Unlike iris tracking, the raw nose position has no natural
  "centered" reading (the nose sits below eye level on every face, not centered on it), so this
  goes through `NoseOffsetTracker`, which reports movement *relative to a captured baseline*
  rather than the raw reading — see "Recenter head position" below.

Both signals return the same shape of value (roughly [-1, 1] per axis, same sign convention), so
either can drive `CursorController`/`GazeCalibration` unchanged — switching the toggle mid-session
just changes which one feeds them from the next frame on.

**Recenter head position** — click this any time nose tracking feels off-center (after shifting in
your seat, leaning back, etc.): it discards `NoseOffsetTracker`'s current baseline, and the very
next frame's nose position becomes the new "centered" reading. The first time nose tracking is
ever used, a baseline is captured automatically the same way — you don't need to click it before
first use, only when your "neutral" position has changed. **This is also the fix for nose
relative movement always dragging the cursor one direction** (nearly always down, since the nose
sits below eye level on every face): without a baseline, that constant per-face anatomical offset
was being read as constant movement every single frame.

**Movement mode** — how an offset becomes cursor motion:

- **Absolute (calibrated)** (default) — needs a calibration for whichever tracking source is
  currently selected (see below); falls back to relative until one exists.
- **Relative (dx/dy)** — the original joystick-style nudge, selectable any time, calibrated or not.

That raw offset alone isn't a screen position — the same offset means a different amount of
screen distance for different people/camera distances, and a different amount for iris vs.
nose/face tracking. **Click "Calibrate gaze" in the app window** to fix that: it shows 5 dots
(center + 4 corners) one at a time; look at each one and press SPACE to record a sample.
[src/gesture_os/calibration.py](src/gesture_os/calibration.py) fits a linear `offset -> screen
pixel` mapping from those samples and saves it to `calibration.json` (not checked into git —
recalibrate any time by clicking the button again). A calibration is tied to whichever tracking
source was active when you made it; switching source afterward needs a fresh calibration for
accurate absolute positioning. Once calibrated (and "Absolute" is selected), the cursor jumps to
an absolute screen position ("look here, cursor goes here") via `CursorController.move_to()`.

In relative mode (selected explicitly, or as the automatic fallback before/without a calibration),
`CursorController.move()` nudges the cursor via `pyautogui.moveRel`, scaled by a per-axis, per-source
**sensitivity** (pixels moved per unit of offset past a shared `deadzone`, default `0.15`) — the
"Relative movement sensitivity" panel in the app window shows only the two fields (X, Y) for
whichever tracking source is currently selected — Iris X/Y while "Iris" is chosen, Nose X/Y while
"Face / nose" is — switching the toggle swaps which pair is visible immediately, since only one of
them is ever relevant to what's currently moving the cursor. **Sign matters, not just magnitude: a
negative value inverts that axis' direction** — the
defaults (`iris: x=-40, y=40`; `nose: x=-400, y=400`) already negate X, since both offset signals
come from a raw, unmirrored camera frame where "look/turn right" maps to *smaller* image x, not
larger (the same root cause as the handedness gotcha in recognizer.py). If movement still feels
backwards or too slow/fast after that, flip the sign or raise the magnitude of whichever axis is
wrong and click "Save settings". Absolute (calibrated) mode doesn't need this: its fitted mapping
self-corrects for both speed and direction from your actual calibration samples.

**"Save settings"** persists everything currently selected — both sensitivity fields *and* the
Tracking source / Movement mode radio buttons — to `settings.json` (not checked into git; see
[src/gesture_os/settings.py](src/gesture_os/settings.py)), and all of it reloads automatically
next run, so a session picks up exactly where you left off. Flipping a radio button or editing a
sensitivity field takes effect immediately in the running app either way; clicking "Save settings"
only controls whether that choice is still there the *next* time you launch it.

Moving the real mouse to a screen corner is pyautogui's built-in panic button — it stops gaze
cursor movement outright (the app catches `FailSafeException` and pauses, same as a fist gesture)
if it ever goes out of control. Make an `open_palm` gesture to resume.

**Cursor smoothness:** pyautogui defaults to a 0.1s pause after *every* call it makes, meant for
scripted automation you can visually track — but `CursorController` calls it once per camera
frame, so that default alone was capping cursor updates to **10 per second**, regardless of
anything else, which is what made movement feel choppy. [actions.py](src/gesture_os/actions.py)
now sets `pyautogui.PAUSE = 0` at import (measured: this alone is a >1000x reduction in per-call
overhead). With that removed, the real ceiling is MediaPipe inference (~10ms for both hand and
face detection combined, measured on a blank frame — real frames may run somewhat slower) plus
your webcam's own frame rate, so cursor updates should now track your actual camera FPS rather
than being artificially capped at 10/sec.

The **"Tick interval (ms)"** field in the "Performance" panel is the other half of this: it's the
minimum delay before the next capture/inference/move cycle after the current one finishes — not a
fixed-rate timer, so if a cycle's own work takes longer than this value, that's the real limit, not
this number. Lower generally means smoother (tries again sooner) at the cost of more CPU use;
1-2ms is already "as fast as this machine's processing allows" for most setups, so raise it instead
if you'd rather trade smoothness for lower CPU usage. Persists with "Save settings" like everything
else here.

`gaze.py`'s `draw_debug_overlay` (imported in `ui/app.py` as `draw_gaze_overlay`) draws exactly
what's being tracked onto the live video feed in the app window: a green dot on each eye-socket
landmark, a red dot on each iris center, a blue dot on the nose tip — all drawn regardless of
which tracking source is currently selected. MediaPipe itself has no built-in display — this
overlay, like the hand one above, is what makes tracking quality visible instead of only
inferable from cursor jitter.
