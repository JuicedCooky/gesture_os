"""Unit tests for the pure calibration fitting/mapping logic (no camera/model)."""

import pytest

from gesture_os.calibration import CalibrationSample, fit_calibration


def _sample(offset: tuple[float, float], screen_point: tuple[int, int]) -> CalibrationSample:
    return CalibrationSample(offset=offset, screen_point=screen_point)


def test_fit_exactly_recovers_a_linear_mapping():
    # screen_x = 400 * offset_x + 400 ; screen_y = 300 * offset_y + 300
    samples = [
        _sample((0.0, 0.0), (400, 300)),
        _sample((-1.0, -1.0), (0, 0)),
        _sample((1.0, 1.0), (800, 600)),
        _sample((-1.0, 1.0), (0, 600)),
        _sample((1.0, -1.0), (800, 0)),
    ]

    calibration = fit_calibration(samples, screen_width=800, screen_height=600)

    assert calibration.to_screen(0.0, 0.0) == (400, 300)
    assert calibration.to_screen(-1.0, -1.0) == (0, 0)
    assert calibration.to_screen(1.0, 1.0) == (800 - 1, 600 - 1)  # clamped to screen bounds


def test_to_screen_clamps_beyond_calibrated_range():
    samples = [
        _sample((0.0, 0.0), (400, 300)),
        _sample((-1.0, -1.0), (0, 0)),
        _sample((1.0, 1.0), (800, 600)),
    ]
    calibration = fit_calibration(samples, screen_width=800, screen_height=600)

    x, y = calibration.to_screen(5.0, 5.0)  # far outside any calibrated offset
    assert x == 800 - 1
    assert y == 600 - 1

    x, y = calibration.to_screen(-5.0, -5.0)
    assert x == 0
    assert y == 0


def test_fit_requires_at_least_two_samples():
    with pytest.raises(ValueError):
        fit_calibration([_sample((0.0, 0.0), (400, 300))], screen_width=800, screen_height=600)
