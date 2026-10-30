'''Read-only soak watcher: samples frames/health on a background thread and reports transitions.

Never sends input. Conditions: blank, freeze, crash_to_home, ds4_lost, session_lost.
An event '<cond>' is emitted when a condition starts and '<cond>_cleared' when it ends.
'''

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

CONDITIONS = ('blank', 'freeze', 'crash_to_home', 'ds4_lost', 'session_lost')
BLANK_STD = 1.0
MOTION_DELTA = 0.5


def _small_gray(frame: np.ndarray) -> np.ndarray:
    g = frame if frame.ndim == 2 else cv2.cvtColor(frame[..., :3], cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)


class Monitor(threading.Thread):
    def __init__(self, grab_fn: Callable[[], np.ndarray | None], interval: float = 2.0,
                 freeze_seconds: float = 30.0, on_event: Callable[[str, dict[str, Any]], None] | None = None,
                 ds4_fn: Callable[[], bool] | None = None, session_fn: Callable[[], bool] | None = None,
                 home_detect_fn: Callable[[np.ndarray], bool] | None = None,
                 expect_motion_fn: Callable[[], bool] = lambda: True,
                 lock: threading.Lock | threading.RLock | None = None) -> None:
        super().__init__(name='ps5-monitor', daemon=True)
        self.grab_fn, self.interval, self.freeze_seconds = grab_fn, interval, freeze_seconds
        self.on_event, self.ds4_fn, self.session_fn = on_event, ds4_fn, session_fn
        self.home_detect_fn, self.expect_motion_fn, self.lock = home_detect_fn, expect_motion_fn, lock
        self.events: list[dict[str, Any]] = []
        self.active: dict[str, bool] = {c: False for c in CONDITIONS}
        self.counts: dict[str, int] = {c: 0 for c in CONDITIONS}
        self.ticks = 0
        self.errors = 0
        self.started_at: float | None = None
        self._stop_evt = threading.Event()
        self._prev: np.ndarray | None = None
        self._last_motion: float | None = None
        self._last_delta: float | None = None

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> None:
        self.started_at = self.started_at or time.time()
        while not self._stop_evt.is_set():
            self.tick()
            self._stop_evt.wait(self.interval)

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop_evt.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout)

    # -- sampling ------------------------------------------------------------
    def _grab(self) -> np.ndarray | None:
        ctx = self.lock if self.lock is not None else contextlib.nullcontext()
        try:
            with ctx:
                return self.grab_fn()
        except Exception as exc:  # noqa: BLE001 - capture errors count as blank
            self._error('grab', exc)
            return None

    def _probe(self, name: str, fn: Callable[..., bool] | None, *args: Any) -> bool | None:
        if fn is None:
            return None
        try:
            return bool(fn(*args))
        except Exception as exc:  # noqa: BLE001
            self._error(name, exc)
            return None

    def _error(self, where: str, exc: Exception) -> None:
        self.errors += 1
        self.last_error = f'{where}: {exc}'

    def tick(self, now: float | None = None) -> None:
        '''One sample. Public so callers/tests can drive the monitor synchronously.'''
        now = time.time() if now is None else now
        self.started_at = self.started_at or now
        self.ticks += 1
        frame = self._grab()
        expecting = self._probe('expect_motion', self.expect_motion_fn) is not False
        blank = frame is None or float(np.std(frame)) < BLANK_STD
        self._set('blank', blank, now, std=None if frame is None else round(float(np.std(frame)), 3))

        frozen = False
        if blank or not expecting:
            self._prev, self._last_motion = None, now
        else:
            cur = _small_gray(frame)  # type: ignore[arg-type]
            if self._prev is None or self._prev.shape != cur.shape:
                self._last_motion = now
            else:
                self._last_delta = float(np.mean(np.abs(cur - self._prev)))
                if self._last_delta > MOTION_DELTA:
                    self._last_motion = now
            self._prev = cur
            frozen = now - (self._last_motion or now) >= self.freeze_seconds
        self._set('freeze', frozen, now, still_for=round(now - (self._last_motion or now), 2),
                  delta=self._last_delta)

        home = False
        if frame is not None and not blank and expecting:
            home = bool(self._probe('home_detect', self.home_detect_fn, frame))
        self._set('crash_to_home', home, now)
        self._set('ds4_lost', self._probe('ds4', self.ds4_fn) is False, now)
        self._set('session_lost', self._probe('session', self.session_fn) is False, now)

    def _set(self, cond: str, value: bool, now: float, **data: Any) -> None:
        if value == self.active[cond]:
            return
        self.active[cond] = value
        if value:
            self.counts[cond] += 1
        self._emit(cond if value else f'{cond}_cleared', now, **data)

    def _emit(self, event: str, now: float, **data: Any) -> None:
        rec = {'event': event, 'ts': round(now, 3),
               't': round(now - (self.started_at or now), 3), **data}
        self.events.append(rec)
        if self.on_event is not None:
            try:
                self.on_event(event, rec)
            except Exception as exc:  # noqa: BLE001 - never kill the watcher
                self._error('on_event', exc)

    # -- results -------------------------------------------------------------
    @property
    def healthy(self) -> bool:
        return not any(self.active.values())

    def summary(self) -> dict[str, Any]:
        now = time.time()
        return {'ticks': self.ticks, 'errors': self.errors,
                'duration': round(now - self.started_at, 3) if self.started_at else 0.0,
                'counts': dict(self.counts), 'active': [c for c, v in self.active.items() if v],
                'healthy': self.healthy, 'events': list(self.events)}
