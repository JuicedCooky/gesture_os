"""Unit tests for ui/app.py's pure helpers (no Tk window, camera, or model —
GestureOsApp itself needs all three, so it's exercised via manual/ad-hoc
verification instead, not pytest)."""

import pytest

from gesture_os.ui.app import _ema


def test_ema_seeds_from_the_first_sample():
    assert _ema(None, 42.0) == 42.0


def test_ema_moves_toward_new_samples_without_jumping_straight_to_them():
    result = _ema(previous=10.0, sample=20.0, alpha=0.1)
    assert 10.0 < result < 20.0


def test_ema_converges_toward_a_sustained_new_value():
    value = 10.0
    for _ in range(200):
        value = _ema(value, 20.0, alpha=0.1)
    assert value == pytest.approx(20.0)
