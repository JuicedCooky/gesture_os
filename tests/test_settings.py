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
    assert settings.nose_deadzone_x == Settings.defaults().nose_deadzone_x
    assert settings.nose_deadzone_y == Settings.defaults().nose_deadzone_y
    assert settings.wink_threshold == Settings.defaults().wink_threshold


def test_save_and_load_round_trip_includes_poll_ms(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        iris=AxisSensitivity(x=-55.0, y=30.0), nose=AxisSensitivity(x=-500.0, y=250.0), poll_ms=5
    )

    save_settings(original, path)
    loaded = load_settings(path)

    assert loaded.poll_ms == 5


def test_save_and_load_round_trip_includes_nose_deadzone_x_and_y_independently(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        iris=AxisSensitivity(x=-55.0, y=30.0),
        nose=AxisSensitivity(x=-500.0, y=250.0),
        nose_deadzone_x=0.35,
        nose_deadzone_y=0.05,
    )

    save_settings(original, path)
    loaded = load_settings(path)

    assert loaded.nose_deadzone_x == 0.35
    assert loaded.nose_deadzone_y == 0.05


def test_load_settings_migrates_an_old_single_nose_deadzone_to_both_axes(tmp_path):
    # A settings.json saved before X/Y were split had one shared value.
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "iris": {"x": -400.0, "y": 400.0},
                "nose": {"x": -400.0, "y": 400.0},
                "nose_deadzone": 0.4,
            }
        )
    )

    settings = load_settings(path)

    assert settings.nose_deadzone_x == 0.4
    assert settings.nose_deadzone_y == 0.4


def test_save_and_load_round_trip_includes_wink_threshold(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        iris=AxisSensitivity(x=-55.0, y=30.0),
        nose=AxisSensitivity(x=-500.0, y=250.0),
        wink_threshold=0.65,
    )

    save_settings(original, path)
    loaded = load_settings(path)

    assert loaded.wink_threshold == 0.65
