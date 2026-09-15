"""Entry point: `python -m gesture_os.main` or the `gesture-os` console script."""

from gesture_os.ui.app import GestureOsApp


def main() -> None:
    GestureOsApp().run()


if __name__ == "__main__":
    main()
