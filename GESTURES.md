# Gesture Mappings

Default bindings from `default_action_map()` in [src/gesture_os/actions.py](src/gesture_os/actions.py).
Gestures are classified in [src/gesture_os/recognizer.py](src/gesture_os/recognizer.py) by the number
of extended fingers on one hand.

| Gesture      | Hand shape                        | Extended fingers | OS action    |
| ------------ | ---------------------------------- | :---------------: | ------------ |
| `fist`       | closed hand                        | 0                  | Mute volume  |
| `point`      | index finger only                  | 1                  | Volume up    |
| `peace`      | index + middle finger               | 2                  | Volume down  |
| `open_palm`  | all five fingers extended          | 5                  | Play / pause |
| `unknown`    | any other count (3 or 4 fingers)   | 3, 4               | No action    |

## Adding or changing a binding

1. Extend the finger-count → gesture name mapping in `HandGestureRecognizer.classify`
   (`src/gesture_os/recognizer.py`) if you're introducing a new gesture.
2. Bind the gesture name to a `pyautogui` call in `default_action_map()`
   (`src/gesture_os/actions.py`).

Keep any new gesture-detection logic in the pure-function layer (alongside
`count_extended_fingers`) so it stays unit-testable without a camera — see
`tests/test_recognizer.py`.

## Cursor movement (gaze, experimental)

Separately from hand gestures, [src/gesture_os/gaze.py](src/gesture_os/gaze.py) moves the mouse
cursor from iris position: `FaceGazeTracker` finds the iris in each eye socket, and `iris_offset`
computes how far off-center it is, in [-1, 1] per axis.

That raw offset alone isn't a screen position — the same offset means a different amount of
screen distance for different people/camera distances. **Click "Calibrate gaze" in the app
window** to fix that: it shows 5 dots (center + 4 corners) one at a time; look at each one and
press SPACE to record a sample. [src/gesture_os/calibration.py](src/gesture_os/calibration.py)
fits a linear `offset -> screen pixel` mapping from those samples and saves it to
`calibration.json` (not checked into git — recalibrate any time by clicking the button again).
Once calibrated, the cursor jumps to an absolute screen position ("look here, cursor goes here")
via `CursorController.move_to()`.

Before calibrating (or if it's deleted), `CursorController.move()` is the fallback: a *relative*
cursor nudge via `pyautogui.moveRel`, scaled by two knobs:

- `deadzone` (default `0.15`) — offsets smaller than this are treated as center/noise and ignored.
- `sensitivity` (default `20.0`) — pixels moved per unit of offset past the deadzone.

Moving the real mouse to a screen corner is pyautogui's built-in panic button — it stops gaze
cursor movement (the app catches `FailSafeException` and falls back to uncalibrated mode) if it
ever goes out of control.

`draw_debug_overlay` draws exactly what's being tracked onto the live video feed in the app
window: a green dot on each eye-socket landmark, a red dot on each iris center. MediaPipe itself
has no built-in display — this overlay is what makes tracking quality visible instead of only
inferable from cursor jitter.
