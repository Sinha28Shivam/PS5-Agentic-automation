"""Game HUD readers driven by the game profile (config/games/<game>/profile.yaml).

A `bar` reader measures the lit fraction of a horizontal health bar. Bars are
read on a thin strip, per-column "lit" (HSV range) then median-filtered so a
character briefly overlapping the bar does not read as damage.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _lit_columns(frame: np.ndarray, bar: dict[str, Any]) -> np.ndarray:
    h, w = frame.shape[:2]
    sx, sy = w / 1920.0, h / 1080.0
    x0, x1 = int(bar["x0"] * sx), int(bar["x1"] * sx)
    y0, y1 = int(bar["y0"] * sy), int(bar["y1"] * sy)
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    lo, hi = bar.get("hsv_lo", [15, 120, 150]), bar.get("hsv_hi", [40, 255, 255])
    m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    cols = (m > 0).mean(axis=0) >= 0.5
    k = int(bar.get("median", 31)) | 1
    return cv2.medianBlur(cols.astype(np.uint8)[None, :] * 255, k)[0] > 0


def bar_fraction(frame: np.ndarray, bar: dict[str, Any]) -> float:
    """Remaining fraction (0..1).

    `drain: left` means the bar empties from its left edge, so health is the
    lit span ending at the right (inner) edge. Small unlit gaps (a fighter's
    head over the bar) are bridged; the first long gap ends the bar.
    """
    lit = _lit_columns(frame, bar)
    if lit.size == 0:
        return 0.0
    seq = lit[::-1] if bar.get("drain", "left") == "left" else lit
    gap_max = int(bar.get("gap_px", 40))
    n = gap = 0
    for i, v in enumerate(seq):
        if v:
            n, gap = i + 1, 0
        else:
            gap += 1
            if gap > gap_max:
                break
    return float(n / lit.size)


def presence(frame: np.ndarray, spec: dict[str, Any]) -> bool:
    """HUD-present test: fraction of HSV-range pixels in a box within [min,max]
    and (optionally) a textured centre (std above center_std)."""
    h, w = frame.shape[:2]
    sx, sy = w / 1920.0, h / 1080.0
    x0, x1, y0, y1 = (int(spec["x0"] * sx), int(spec["x1"] * sx),
                      int(spec["y0"] * sy), int(spec["y1"] * sy))
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    lo, hi = spec.get("hsv_lo", [15, 100, 120]), spec.get("hsv_hi", [35, 255, 255])
    frac = float((cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8)) > 0).mean())
    if not spec.get("min", 0.0) <= frac <= spec.get("max", 1.0):
        return False
    c = spec.get("center")
    if c:
        g = cv2.cvtColor(frame[int(c["y0"] * sy):int(c["y1"] * sy),
                               int(c["x0"] * sx):int(c["x1"] * sx)], cv2.COLOR_BGR2GRAY)
        return float(g.std()) >= float(c.get("min_std", 0))
    return True


def read_hud(frame: np.ndarray, profile: dict[str, Any]) -> dict[str, float]:
    """Bars as 0..1 fractions; presence checks as 1.0/0.0. Bars read 0 when a
    declared `in_fight` presence check fails (cutscene, menu, pause)."""
    out: dict[str, float] = {}
    specs = profile.get("hud", {}) or {}
    for name, spec in specs.items():
        if spec.get("type") == "presence":
            out[name] = 1.0 if presence(frame, spec) else 0.0
    gate = out.get("in_fight", 1.0)
    for name, spec in specs.items():
        if spec.get("type") == "bar":
            out[name] = round(bar_fraction(frame, spec), 3) if gate else 0.0
    return out


def read_hud_stable(frames: list[np.ndarray], profile: dict[str, Any]) -> dict[str, float]:
    """Median over several frames - robust to momentary occlusion."""
    reads = [read_hud(f, profile) for f in frames if f is not None]
    if not reads:
        return {}
    return {k: round(float(np.median([r[k] for r in reads])), 3) for k in reads[0]}
