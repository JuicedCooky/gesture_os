"""Persists per-tracking-source relative-movement sensitivity settings.

Two independent (x, y) sensitivity pairs — one for iris tracking, one for
face/nose tracking — since the two offset signals (see gaze.py) have very
different natural ranges and users may want to tune, or invert, each
independently. Saved locally to `settings.json` (gitignored) so tuning
survives between runs.

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

    @staticmethod
    def defaults() -> Settings:
        return Settings(
            iris=AxisSensitivity(x=-40.0, y=40.0),
            nose=AxisSensitivity(x=-400.0, y=400.0),
        )


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    """Load saved settings, or defaults if none have been saved yet."""
    if not path.exists():
        return Settings.defaults()
    data = json.loads(path.read_text())
    return Settings(iris=AxisSensitivity(**data["iris"]), nose=AxisSensitivity(**data["nose"]))


def save_settings(settings: Settings, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    path.write_text(json.dumps({"iris": asdict(settings.iris), "nose": asdict(settings.nose)}))
