'''Perception facade: frame -> ScreenState (blank check, OCR signatures, vision fallback).'''

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any, Literal

import cv2
import numpy as np

from ..core import llm
from ..core.evidence import Evidence, frame_hash
from ..core.settings import get_settings
from ..core.state import ScreenState
from . import ocr, signatures, vision

VisionMode = Literal['auto', 'always', 'never']


def _gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY if frame.shape[2] == 4 else cv2.COLOR_BGR2GRAY)


def delta(a: np.ndarray, b: np.ndarray) -> float:
    '''Mean absolute grayscale difference (0..255); frames resized to a common size.'''
    ga, gb = _gray(a), _gray(b)
    if ga.shape != gb.shape:
        gb = cv2.resize(gb, (ga.shape[1], ga.shape[0]), interpolation=cv2.INTER_AREA)
    return float(cv2.absdiff(ga, gb).mean())


def changed(a: np.ndarray, b: np.ndarray, threshold: float = 0.5) -> tuple[bool, float]:
    d = delta(a, b)
    return d >= threshold, d


def frozen(frames: list[np.ndarray], threshold: float = 0.5) -> bool:
    '''True if every consecutive pair differs by less than threshold (needs >= 2 frames).'''
    if len(frames) < 2:
        return False
    return all(delta(a, b) < threshold for a, b in zip(frames, frames[1:]))


def is_blank(frame: np.ndarray, threshold: float | None = None) -> bool:
    if threshold is None:
        threshold = float(get_settings().get('verification.blank_std_threshold', 1.0))
    return frame is None or frame.size == 0 or float(_gray(frame).std()) < threshold


class Perception:
    def __init__(self, cache_size: int = 32):
        self._cache: OrderedDict[tuple[str, str, str], ScreenState] = OrderedDict()
        self._cache_size = cache_size

    @staticmethod
    def _key(frame: np.ndarray, fh: str, use_vision: str) -> tuple[str, str, str]:
        fine = hashlib.blake2b(np.ascontiguousarray(frame[::4, ::4]).tobytes(),
                               digest_size=8).hexdigest()
        return fh, fine, use_vision

    def observe(self, frame: np.ndarray, evidence: Evidence | None = None,
                use_vision: VisionMode = 'auto', tag: str = '') -> ScreenState:
        fh = frame_hash(frame) if frame is not None and frame.size else None
        key = self._key(frame, fh, use_vision) if fh else None
        if key and key in self._cache:
            self._cache.move_to_end(key)
            state = self._cache[key].model_copy(deep=True)
        else:
            state = self._analyse(frame, fh, use_vision)
            if key:
                self._cache[key] = state.model_copy(deep=True)
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        if evidence is not None and fh:
            state.frame_path = evidence.save_frame(frame, tag or state.screen_id)
        return state

    def _analyse(self, frame: np.ndarray, fh: str | None, use_vision: str) -> ScreenState:
        if fh is None or is_blank(frame):
            return ScreenState(frame_hash=fh, blank=True, confidence=1.0)
        text = ocr.read_text(frame)
        screens = signatures.load_screens()
        ranked = signatures.match(text, screens)
        extras: dict[str, Any] = {'candidates': ranked[:5], 'danger': signatures.danger_screen(text)}
        state = ScreenState(frame_hash=fh, text=text, extras=extras)
        hit = signatures.best(text, screens)
        if hit:
            state.screen_id, state.confidence, state.source = hit[0], hit[1], 'signature'
            if screens[hit[0]].danger:
                extras['danger'] = screens[hit[0]].danger
        want = use_vision == 'always' or (use_vision == 'auto' and not hit)
        if want and llm.available():
            v = vision.describe(frame, screens=list(screens))
            if v:
                extras['vision'] = v
                state.description, state.focused = v['description'], v['focused']
                if not hit:
                    state.screen_id, state.confidence, state.source = (
                        v['screen_id'], v['confidence'], 'vision')
        return state

    def clear(self) -> None:
        self._cache.clear()
