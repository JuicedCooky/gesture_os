"""Persists the user's cursor-control preferences: per-source relative-
movement sensitivity, the last-used tracking source and movement mode, and
the tick-loop poll interval (see `poll_ms` below).

Two independent (x, y) sensitivity pairs — one for iris tracking, one for
face/nose tracking — since the two offset signals (see gaze.py) have very
different natural ranges and users may want to tune, or invert, each
independently. Saved locally to `settings.json` (gitignored) so tuning
survives between runs; `GestureOsApp` restores `tracking_source`/
`movement_mode` at startup too, so a session picks up where you left off.

Sign matters, not just magnitude: a negative value on an axis inverts that
axis' relative-movement direction. Both offset signals come from a raw
(unmirrored) camera frame — the same root cause as the handedness gotcha in
recognizer.py — so without correction, "look/turn right" maps to *smaller*
image x, not larger; the defaults below use a negative x to correct for
that. Calibrated absolute mode doesn't need this: its fitted mapping
(GazeCalibration) self-corrects for sign from real samples either way.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# <repo root>/settings.json — not checked into git, see .gitignore.
DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"


@dataclass
class AxisSensitivity:
    """Relative-movement gain per axis: pixels moved per unit of offset
    past the deadzone. Negative inverts that axis' direction."""

    x: float
    y: float


@dataclass
class Settings:
    iris: AxisSensitivity
    nose: AxisSensitivity
    tracking_source: str = "iris"  # "iris" or "nose"
    movement_mode: str = "absolute"  # "absolute" or "relative"
    # Minimum delay (ms) before scheduling the next capture/inference/move
    # tick after the current one finishes — not a fixed-rate timer; if a
    # tick's own work takes longer than this, that's the real limit, not
    # this number (see ui/app.py's _tick). Lower = tries to update sooner;
    # only matters once actual per-tick processing is faster than this.
    poll_ms: int = 1
    # Nose/face relative-movement deadzone, independent per axis: offset
    # smaller than this on that axis (in the same units as nose_offset's
    # roughly-[-1, 1] range) is treated as center/noise and doesn't move
    # the cursor on that axis at all. Adjustable via two sliders in the app
    # window, next to the sensitivity fields — nose tracking only for now
    # (iris keeps CursorController.move's built-in default) since head
    # position tends to be noisier at rest than iris.
    nose_deadzone_x: float = 0.15
    nose_deadzone_y: float = 0.15
    # How closed an eye's "eyeBlinkLeft"/"eyeBlinkRight" blendshape score
    # (0=open, 1=fully closed) must be to count as a deliberate wink for
    # click detection (see gaze.detect_wink). A real portrait with both
    # eyes open measured ~0.26-0.27 on this scale; 0.5 leaves margin above
    # normal open-eye noise without requiring a maximally scrunched wink.
    wink_threshold: float = 0.5

    @staticmethod
    def defaults() -> Settings:
        return Settings(
            iris=AxisSensitivity(x=-40.0, y=40.0),
            nose=AxisSensitivity(x=-400.0, y=400.0),
            tracking_source="iris",
            movement_mode="absolute",
            poll_ms=1,
            nose_deadzone_x=0.15,
            nose_deadzone_y=0.15,
            wink_threshold=0.5,
        )


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    """Load saved settings, or defaults if none have been saved yet."""
    if not path.exists():
        return Settings.defaults()
    data = json.loads(path.read_text())
    defaults = Settings.defaults()
    # A settings.json saved before X/Y were split had one "nose_deadzone"
    # key shared by both axes; use it as the fallback for each axis so an
    # older file migrates to the same behavior it had before, rather than
    # silently resetting to the (different) default.
    old_deadzone = data.get("nose_deadzone")
    deadzone_x_fallback = defaults.nose_deadzone_x if old_deadzone is None else old_deadzone
    deadzone_y_fallback = defaults.nose_deadzone_y if old_deadzone is None else old_deadzone
    return Settings(
        iris=AxisSensitivity(**data["iris"]),
        nose=AxisSensitivity(**data["nose"]),
        # .get with a fallback: a settings.json saved before these fields
        # existed shouldn't fail to load, just fall back to the default mode.
        tracking_source=data.get("tracking_source", defaults.tracking_source),
        movement_mode=data.get("movement_mode", defaults.movement_mode),
        poll_ms=data.get("poll_ms", defaults.poll_ms),
        nose_deadzone_x=data.get("nose_deadzone_x", deadzone_x_fallback),
        nose_deadzone_y=data.get("nose_deadzone_y", deadzone_y_fallback),
        wink_threshold=data.get("wink_threshold", defaults.wink_threshold),
    )


def save_settings(settings: Settings, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    path.write_text(
        json.dumps(
            {
                "iris": asdict(settings.iris),
                "nose": asdict(settings.nose),
                "tracking_source": settings.tracking_source,
                "movement_mode": settings.movement_mode,
                "poll_ms": settings.poll_ms,
                "nose_deadzone_x": settings.nose_deadzone_x,
                "nose_deadzone_y": settings.nose_deadzone_y,
                "wink_threshold": settings.wink_threshold,
            }
        )
    )
