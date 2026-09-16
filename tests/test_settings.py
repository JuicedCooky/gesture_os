"""Unit tests for the persisted per-source sensitivity settings (no UI)."""

import json
from pathlib import Path

from gesture_os.settings import AxisSensitivity, Settings, load_settings, save_settings


def test_load_settings_without_a_saved_file_returns_defaults():
    missing_path = Path("this/path/does/not/exist/settings.json")
    settings = load_settings(missing_path)
    assert settings == Settings.defaults()


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        iris=AxisSensitivity(x=-55.0, y=30.0), nose=AxisSensitivity(x=-500.0, y=250.0)
    )

    save_settings(original, path)
    loaded = load_settings(path)

    assert loaded == original


def test_iris_and_nose_sensitivities_are_independent():
    settings = Settings.defaults()
    assert settings.iris != settings.nose


def test_save_and_load_round_trip_includes_tracking_source_and_movement_mode(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        iris=AxisSensitivity(x=-55.0, y=30.0),
        nose=AxisSensitivity(x=-500.0, y=250.0),
        tracking_source="nose",
        movement_mode="relative",
    )

    save_settings(original, path)
    loaded = load_settings(path)

    assert loaded == original


def test_load_settings_fills_in_missing_fields_from_an_older_file(tmp_path):
    # A settings.json saved before tracking_source/movement_mode/poll_ms existed.
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"iris": {"x": -400.0, "y": 400.0}, "nose": {"x": -400.0, "y": 400.0}})
    )

    settings = load_settings(path)

    assert settings.iris == AxisSensitivity(x=-400.0, y=400.0)
    assert settings.tracking_source == Settings.defaults().tracking_source
    assert settings.movement_mode == Settings.defaults().movement_mode
    assert settings.poll_ms == Settings.defaults().poll_ms


def test_save_and_load_round_trip_includes_poll_ms(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        iris=AxisSensitivity(x=-55.0, y=30.0), nose=AxisSensitivity(x=-500.0, y=250.0), poll_ms=5
    )

    save_settings(original, path)
    loaded = load_settings(path)

    assert loaded.poll_ms == 5
