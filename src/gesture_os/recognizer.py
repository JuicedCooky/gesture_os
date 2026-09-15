"""Hand landmark detection (MediaPipe Tasks) and gesture classification.

Classification is split into two layers on purpose:

- `count_extended_fingers` is pure geometry over landmark coordinates, with
  no dependency on MediaPipe itself, so it can be unit tested with synthetic
  landmark data (see tests/test_recognizer.py).
- `HandGestureRecognizer` wraps the actual MediaPipe `HandLandmarker` task
  and feeds its output through the pure classification logic.

Note: import Tasks submodules with `from mediapipe.tasks.python import vision`
(not `import mediapipe.tasks.python.vision as vision`) — the latter raises a
spurious `ImportError: cannot import name 'python' from 'mediapipe.tasks.python'`
due to an attribute-resolution quirk in this MediaPipe build.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

# <repo root>/models/hand_landmarker.task — fetched by scripts/download_models.py.
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "hand_landmarker.task"


@dataclass(frozen=True)
class Hand:
    """A single detected hand's landmarks, normalized to [0, 1] image coords."""

    landmarks: list[tuple[float, float, float]]
    handedness: str  # "Left" or "Right", as reported by MediaPipe


def count_extended_fingers(hand: Hand) -> int:
    """Count how many fingers are extended, using landmark geometry alone."""
    lm = hand.landmarks
    extended = 0

    # Thumb: compare x position against its own knuckle, mirrored by handedness.
    thumb_tip, thumb_ip = lm[4], lm[3]
    if hand.handedness == "Right":
        extended += thumb_tip[0] < thumb_ip[0]
    else:
        extended += thumb_tip[0] > thumb_ip[0]

    # Other four fingers: tip above its own middle knuckle means "extended".
    for tip_id in (8, 12, 16, 20):
        pip_id = tip_id - 2
        extended += lm[tip_id][1] < lm[pip_id][1]

    return extended


class HandGestureRecognizer:
    """Wraps MediaPipe's HandLandmarker task and classifies simple gestures."""

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        max_hands: int = 1,
        min_detection_confidence: float = 0.7,
    ) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Hand landmark model not found at {model_path}. "
                "Run `python scripts/download_models.py` to fetch it."
            )
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=min_detection_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, frame_rgb) -> list[Hand]:
        """Run detection on an RGB frame and return the hands found."""
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # VIDEO mode requires strictly increasing timestamps; a wall-clock
        # reading can repeat within the same millisecond, so clamp forward.
        timestamp_ms = max(time.monotonic_ns() // 1_000_000, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        result = self._landmarker.detect_for_video(image, timestamp_ms)
        hands: list[Hand] = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            points = [(p.x, p.y, p.z) for p in landmarks]
            label = handedness[0].category_name
            hands.append(Hand(landmarks=points, handedness=label))
        return hands

    def classify(self, hand: Hand) -> str:
        """Map a hand's extended-finger count to a named gesture."""
        count = count_extended_fingers(hand)
        return {
            0: "fist",
            1: "point",
            2: "peace",
            5: "open_palm",
        }.get(count, "unknown")

    def close(self) -> None:
        self._landmarker.close()
