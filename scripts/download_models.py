"""Downloads the MediaPipe model assets into models/.

Run once after installing dependencies:

    python scripts/download_models.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

MODEL_URLS = {
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/latest/hand_landmarker.task"
    ),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/latest/face_landmarker.task"
    ),
}


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in MODEL_URLS.items():
        path = MODELS_DIR / filename
        if path.exists():
            print(f"Already present: {path}")
            continue
        print(f"Downloading {url} -> {path}")
        urllib.request.urlretrieve(url, path)
    print("Done.")


if __name__ == "__main__":
    main()
