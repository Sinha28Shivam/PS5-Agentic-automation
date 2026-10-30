"""Evidence store: saves frames and a JSONL event log under artifacts/runs/<run_id>/."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def frame_hash(frame: np.ndarray) -> str:
    """Perceptual-ish hash: 32x18 grayscale, robust to tiny noise."""
    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 18),
                       interpolation=cv2.INTER_AREA)
    q = (small // 16).astype(np.uint8)
    return hashlib.sha1(q.tobytes()).hexdigest()[:16]


class Evidence:
    def __init__(self, run_dir: Path | str):
        self.dir = Path(run_dir)
        self.frames = self.dir / "frames"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.log_path = self.dir / "events.jsonl"
        self._n = 0

    def save_frame(self, frame: np.ndarray, tag: str) -> str:
        self._n += 1
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:40]
        path = self.frames / f"{self._n:04d}-{safe}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return str(path)

    def log(self, event: str, **data: Any) -> None:
        rec = {"ts": round(time.time(), 3), "event": event, **data}
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    def write_json(self, name: str, obj: Any) -> str:
        path = self.dir / name
        path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
        return str(path)
