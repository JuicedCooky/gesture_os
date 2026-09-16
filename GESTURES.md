# Gesture Mappings

Default bindings from `default_action_map()` in [src/gesture_os/actions.py](src/gesture_os/actions.py),
plus two bound directly in [src/gesture_os/ui/app.py](src/gesture_os/ui/app.py) since they control
app state rather than firing a stateless OS action. Gestures are classified in
[src/gesture_os/recognizer.py](src/gesture_os/recognizer.py) by the number of extended fingers on
one hand.

| Gesture      | Hand shape                        | Extended fingers | Action                        |
| ------------ | ---------------------------------- | :---------------: | ------------------------------ |
| `fist`       | closed hand                        | 0                  | **Pause** gaze cursor          |
| `point`      | index finger only                  | 1                  | *(unbound)*                    |
| `peace`      | index + middle finger               | 2                  | **Recenter head position**     |
| `open_palm`  | all five fingers extended          | 5                  | **Resume** gaze cursor         |
| `unknown`    | any other count (3 or 4 fingers)   | 3, 4               | No action                      |

`point`/`peace` previously triggered volume up/down; that binding was removed. `peace` was later
rebound to recenter head/nose tracking (same as the "Recenter head position" button — see Cursor
movement below); `point` is still unbound — see "Adding or changing a binding" below to rebind it.

Pausing/resuming only stops cursor *movement* — the video feed, iris tracking, and its debug
overlay keep running the whole time, and fist/peace/point still fire while paused. Current state
shows in its own "gaze: active/paused" label in the app window (see Cursor movement below), kept
separate from the general status line so it's never overwritten by other status messages.

The large **Mouse Control: ON/OFF** button at the top of the app window does the exact same
pause/resume as `fist`/`open_palm` — it's a second way to reach the same on/off state (for when
gesturing isn't convenient), not a separate switch. Whichever one you use last — gesture or
button — is reflected in both: the button's label/color and the "gaze:" status line always agree.

**"Show gesture guide"** opens a small reference window listing every gesture/wink and what it
currently does — this table, condensed. Click it again (or if it's still open) to bring the same
window to front rather than opening a duplicate; closing it and clicking again opens a fresh one.
It's a fixed lookup table in [ui/app.py](src/gesture_os/ui/app.py) (`_GESTURE_GUIDE`), not a live
introspection of the real bindings, so if you rebind a gesture (see "Adding or changing a binding"
below) update that table by hand too or the guide will drift from what actually happens.

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

**Recenter head position** — click this button, or make a `peace` gesture (either does the exact
same thing), any time nose tracking feels off-center (after shifting in your seat, leaning back,
etc.): it discards `NoseOffsetTracker`'s current baseline, and the very next frame's nose position
becomes the new "centered" reading. The first time nose tracking is ever used, a baseline is
captured automatically the same way — you don't need to trigger it before first use, only when
your "neutral" position has changed. **This is also the fix for nose relative movement always
dragging the cursor one direction** (nearly always down, since the nose sits below eye level on
every face): without a baseline, that constant per-face anatomical offset was being read as
constant movement every single frame.

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
**sensitivity** (pixels moved per unit of offset past a **deadzone**) — the "Relative movement
sensitivity" panel in the app window shows only the fields for whichever tracking source is
currently selected — Iris X/Y while "Iris" is chosen, Nose X/Y (plus a **Nose deadzone slider**,
see below) while "Face / nose" is — switching the toggle swaps which is visible immediately, since
only one is ever relevant to what's currently moving the cursor. **Sign matters, not just
magnitude: a negative value inverts that axis' direction** — the
defaults (`iris: x=-40, y=40`; `nose: x=-400, y=400`) already negate X, since both offset signals
come from a raw, unmirrored camera frame where "look/turn right" maps to *smaller* image x, not
larger (the same root cause as the handedness gotcha in recognizer.py). If movement still feels
backwards or too slow/fast after that, flip the sign or raise the magnitude of whichever axis is
wrong and click "Save settings". Absolute (calibrated) mode doesn't need this: its fitted mapping
self-corrects for both speed and direction from your actual calibration samples.

**Nose deadzone X / Y sliders** (next to the Nose X/Y sensitivity fields, only shown in nose
tracking mode): how far off-center your nose has to move on *that axis* before the cursor starts
moving on it at all — independent per axis, since a face can jitter more on one axis than the
other at rest (e.g. more horizontal wobble than vertical), and you may want one axis more forgiving
than the other without dulling the other's response. Raise an axis's deadzone if small jitter on it
nudges the cursor when you don't want it to; lower it if that axis feels sluggish to start moving.
Both are sliders (range 0-0.5, live-updating labels showing the current values), not free-text
fields, since the values only make sense within that range. Iris tracking doesn't have its own
sliders yet — it uses `CursorController.move`'s built-in default (`0.15` for both axes) regardless
of these.

**"Save settings"** persists everything currently selected — both sensitivity fields, both nose
deadzone sliders, the tick interval, *and* the Tracking source / Movement mode radio buttons — to
`settings.json` (not checked into git; see [src/gesture_os/settings.py](src/gesture_os/settings.py)),
and all of it reloads automatically next run, so a session picks up exactly where you left off.
Flipping a radio button, moving the slider, or editing a sensitivity field takes effect immediately
in the running app either way; clicking "Save settings"
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

Right below it, **"Actual tick rate"** shows the *real*, currently measured rate (smoothed, so one
stray slow/fast tick doesn't make it jump around) — e.g. "8.3 ms/tick (~120 fps)". This is wall-clock
time for the whole loop (camera read + both MediaPipe inferences + drawing + the delay itself), not
just the "Tick interval" setting, so it's the honest number to check if movement feels like it's
slowed down: if this reading has dropped noticeably from what it normally reads, something in that
loop (camera, CPU load from another program, thermal throttling, etc.) is the actual bottleneck —
not necessarily anything in this app's own code. Resets to "(warming up...)" on stop/restart so a
paused gap never gets counted as one enormous "tick."

`gaze.py`'s `draw_debug_overlay` (imported in `ui/app.py` as `draw_gaze_overlay`) draws exactly
what's being tracked onto the live video feed in the app window: a green dot on each eye-socket
landmark, a red dot on each iris center, a blue dot on the nose tip — all drawn regardless of
which tracking source is currently selected. MediaPipe itself has no built-in display — this
overlay, like the hand one above, is what makes tracking quality visible instead of only
inferable from cursor jitter.

## Wink to click

Winking one eye alone — not blinking both together — fires a mouse click: **left** eye triggers a
**left** click, **right** eye a **right** click. This runs independently of the gesture/cursor
toggles above (works regardless of which tracking source or movement mode is selected), and is
suppressed while "Mouse Control" is off (the big button, or a `fist` gesture) — same as cursor
movement, since a click is also a form of mouse control.

The signal is MediaPipe's own `eyeBlinkLeft`/`eyeBlinkRight` blendshapes (one of 52 named
facial-expression scores the Face Landmarker model outputs directly, 0 = open to 1 = fully
closed) — not geometry computed from landmarks by this code, and more robust than that would be.
`gaze.detect_wink(face, threshold)` reports "left"/"right" only when *one* eye is closed past
threshold and the other isn't — both eyes closing together is treated as an ordinary blink and
deliberately produces no click.

**Wink threshold** slider (range 0-1, live-updating label): how closed an eye's blendshape score
must be to count as "closed" for wink purposes. Lower it if genuine winks aren't registering,
raise it if it's firing on partial eye narrowing you didn't intend as a wink. A real test photo
with both eyes normally open measured ~0.27 on this scale, so the default of `0.5` leaves
meaningful margin above ordinary open-eye noise. Persists with "Save settings" like everything
else in this document.

A click only fires once per wink, not once per frame the eye stays shut — `gaze.WinkClickDetector`
tracks the *transition* into a wink (open → closed), not just "is currently closed", so holding a
wink for half a second doesn't fire a dozen clicks. Release (open both eyes, or switch which eye
you're winking) before the next wink will register again.
