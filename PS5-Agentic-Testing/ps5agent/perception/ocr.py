'''OCR for PS5 frames: grayscale + Otsu (normal and inverted passes) with an LRU cache.'''

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import cv2
import numpy as np
import pytesseract

from ..core.evidence import frame_hash

TESSERACT_EXE = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
MAX_WIDTH = 1280
SMALL_WIDTH = 640
BRIGHT_THRESHOLD = 140
CACHE_SIZE = 64
TESS_CONFIG = '--oem 3 --psm 11'

_cache: OrderedDict[tuple[Any, ...], str] = OrderedDict()

if not shutil.which('tesseract') and os.path.isfile(TESSERACT_EXE):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


def available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def normalise(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().lower()


def crop(frame: np.ndarray, region: dict[str, Any] | None) -> np.ndarray:
    '''Crop by fractional region {x, y, width, height}.'''
    if not region:
        return frame
    h, w = frame.shape[:2]
    x = min(max(float(region.get('x', 0.0)), 0.0), 1.0)
    y = min(max(float(region.get('y', 0.0)), 0.0), 1.0)
    rw = min(max(float(region.get('width', 1.0 - x)), 0.0), 1.0 - x)
    rh = min(max(float(region.get('height', 1.0 - y)), 0.0), 1.0 - y)
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = max(x0 + 1, int((x + rw) * w)), max(y0 + 1, int((y + rh) * h))
    return frame[y0:y1, x0:x1]


def preprocess(img: np.ndarray) -> tuple[np.ndarray, ...]:
    '''(otsu, inverted otsu, bright-text mask); full frames downscaled, small crops upscaled 2x.'''
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY if img.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    h, w = gray.shape[:2]
    if w > MAX_WIDTH:
        gray = cv2.resize(gray, (MAX_WIDTH, max(1, int(h * MAX_WIDTH / w))),
                          interpolation=cv2.INTER_AREA)
    elif w < SMALL_WIDTH:
        gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    otsu, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Otsu on dark crops can split at the panel background; a fixed cut isolates light UI text.
    _, bright = cv2.threshold(gray, max(otsu, BRIGHT_THRESHOLD), 255, cv2.THRESH_BINARY_INV)
    return binary, cv2.bitwise_not(binary), bright


def _merge(texts: list[str]) -> str:
    lines: list[str] = []
    for t in texts:
        for line in t.splitlines():
            line = normalise(line)
            if line and line not in lines:
                lines.append(line)
    return ' '.join(lines)


def _key(frame: np.ndarray, img: np.ndarray, region: dict[str, Any] | None) -> tuple[Any, ...]:
    # frame_hash is coarse (32x18); add a cheap digest so small text changes are not served stale.
    digest = hashlib.blake2b(np.ascontiguousarray(img[::4, ::4]).tobytes(), digest_size=8).hexdigest()
    reg = tuple(sorted((str(k), float(v)) for k, v in region.items())) if region else None
    return frame_hash(frame), reg, digest


def read_text(frame: np.ndarray, region: dict[str, Any] | None = None) -> str:
    '''OCR a frame (or fractional region). Returns lower-cased, whitespace-normalised text.'''
    img = crop(frame, region)
    key = _key(frame, img, region)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    with ThreadPoolExecutor(max_workers=3) as pool:
        texts = list(pool.map(lambda b: pytesseract.image_to_string(b, config=TESS_CONFIG),
                              preprocess(img)))
    text = _merge(texts)
    _cache[key] = text
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return text


def clear_cache() -> None:
    _cache.clear()
