"""Webcam capture wrapper around OpenCV's VideoCapture."""

from __future__ import annotations

import cv2


class WebcamCapture:
    """Opens a webcam device and yields BGR frames."""

    def __init__(self, device_index: int = 0) -> None:
        self.device_index = device_index
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.device_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open webcam at index {self.device_index}")

    def read(self):
        """Return the next frame, or None if the capture isn't open / read failed."""
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> WebcamCapture:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
