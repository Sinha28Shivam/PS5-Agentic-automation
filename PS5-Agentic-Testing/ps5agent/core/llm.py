"""Claude access for agents: text + vision, JSON replies, model tiers, call metrics.

Tiers (settings.yaml llm.tiers): "fast" for per-step perception/navigation,
"strong" for planning/judging. Uses the anthropic SDK directly - simple and
gives exact token counts.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from typing import Any

import cv2
import numpy as np

from .settings import get_settings

_lock = threading.Lock()
METRICS: dict[str, Any] = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                           "seconds": 0.0, "errors": 0}


class LLMUnavailable(RuntimeError):
    pass


def _model_for(tier: str) -> str:
    s = get_settings()
    tiers = s.get("llm.tiers", {}) or {}
    default = s.get("llm.providers.anthropic.params.model", "claude-haiku-4-5-20251001")
    return str(tiers.get(tier) or default)


def available() -> bool:
    s = get_settings()                    # loads .env first
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and not s.dry_run


def encode_frame(frame: np.ndarray, max_w: int = 1280) -> str:
    h, w = frame.shape[:2]
    if w > max_w:
        frame = cv2.resize(frame, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("could not encode frame")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _extract_json(text: str) -> Any:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(text[start:])
    return obj


def ask(prompt: str, *, system: str = "", frames: list[np.ndarray] | None = None,
        tier: str = "fast", max_tokens: int = 1024, want_json: bool = True,
        retries: int = 2) -> Any:
    """Send prompt (+ optional frames). Returns parsed JSON (or text)."""
    if not available():
        raise LLMUnavailable("ANTHROPIC_API_KEY not set or dry_run enabled")
    import anthropic

    client = anthropic.Anthropic()
    content: list[dict[str, Any]] = []
    for f in frames or []:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": encode_frame(f)}})
    content.append({"type": "text", "text": prompt + (
        "\n\nReply with ONLY a JSON object." if want_json else "")})
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            resp = client.messages.create(
                model=_model_for(tier), max_tokens=max_tokens, temperature=0,
                system=system or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": content}])
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            with _lock:
                METRICS["calls"] += 1
                METRICS["input_tokens"] += resp.usage.input_tokens
                METRICS["output_tokens"] += resp.usage.output_tokens
                METRICS["seconds"] += time.time() - t0
            return _extract_json(text) if want_json else text
        except Exception as exc:  # noqa: BLE001 - network/parse errors retried
            last_err = exc
            with _lock:
                METRICS["errors"] += 1
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM call failed: {last_err}")


def snapshot_metrics() -> dict[str, Any]:
    with _lock:
        return dict(METRICS)
