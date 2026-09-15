"""Calibrates a linear mapping from iris_offset (see gaze.py) to absolute
screen coordinates.

Raw iris offsets aren't precise enough to map to screen pixels without
per-user, per-camera-distance calibration — the same offset means a
different amount of screen distance for different people/setups. This
module fits that mapping from a handful of "look at this point" samples.

Two-layer split again:

- `fit_calibration` and `GazeCalibration.to_screen` are pure — testable with
  synthetic samples (see tests/test_calibration.py).
- `save_calibration` / `load_calibration` persist a fitted calibration to
  disk (JSON) so a user doesn't need to recalibrate every run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# <repo root>/calibration.json — not checked into git, see .gitignore.
DEFAULT_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "calibration.json"


@dataclass(frozen=True)
class CalibrationSample:
    """One (iris_offset, known screen point) pair, captured while the user
    looked directly at `screen_point`."""

    offset: tuple[float, float]
    screen_point: tuple[int, int]


@dataclass(frozen=True)
class GazeCalibration:
    """A fitted affine mapping from iris offset to screen pixels: one
    scale+bias pair per axis, screen = offset * scale + bias, clamped to
    the screen bounds it was fitted for."""

    scale_x: float
    bias_x: float
    scale_y: float
    bias_y: float
    screen_width: int
    screen_height: int

    def to_screen(self, offset_x: float, offset_y: float) -> tuple[int, int]:
        """Map an iris offset to a screen point, clamped to the screen."""
        x = round(offset_x * self.scale_x + self.bias_x)
        y = round(offset_y * self.scale_y + self.bias_y)
        x = max(0, min(self.screen_width - 1, x))
        y = max(0, min(self.screen_height - 1, y))
        return x, y


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope/intercept for ys ~= slope * xs + intercept."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        # All samples had the same offset on this axis (e.g. no eye movement
        # was captured) — nothing to fit; fall back to a fixed midpoint.
        return 0.0, mean_y
    slope = covariance / variance
    intercept = mean_y - slope * mean_x
    return slope, intercept


def fit_calibration(
    samples: list[CalibrationSample], screen_width: int, screen_height: int
) -> GazeCalibration:
    """Fit a GazeCalibration from calibration samples via linear least squares.

    Needs at least 2 samples with distinct offsets to fit a meaningful slope
    on each axis; a standard multi-point calibration (e.g. center + 4
    corners) comfortably satisfies this.
    """
    if len(samples) < 2:
        raise ValueError("Need at least 2 calibration samples")
    offsets_x = [s.offset[0] for s in samples]
    offsets_y = [s.offset[1] for s in samples]
    screens_x = [s.screen_point[0] for s in samples]
    screens_y = [s.screen_point[1] for s in samples]
    scale_x, bias_x = _linear_fit(offsets_x, screens_x)
    scale_y, bias_y = _linear_fit(offsets_y, screens_y)
    return GazeCalibration(scale_x, bias_x, scale_y, bias_y, screen_width, screen_height)


def save_calibration(calibration: GazeCalibration, path: Path = DEFAULT_CALIBRATION_PATH) -> None:
    path.write_text(json.dumps(asdict(calibration)))


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> GazeCalibration | None:
    """Load a previously saved calibration, or None if none exists yet."""
    if not path.exists():
        return None
    return GazeCalibration(**json.loads(path.read_text()))
