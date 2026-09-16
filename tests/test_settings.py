"""Unit tests for the persisted per-source sensitivity settings (no UI)."""

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
