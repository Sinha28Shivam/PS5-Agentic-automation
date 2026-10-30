'''Vision-LLM perception: describe a frame and judge before/after claims.'''

from __future__ import annotations

import json
from typing import Any

import numpy as np

from ..core import llm

SYSTEM = (
    'You are the eyes of an automated PlayStation 5 test rig. Every image is a frame captured '
    'from the console HDMI output via a capture card (a TV picture, 16:9). Describe only what is '
    'actually visible; never guess hidden state. The PS5 UI usually shows light text on a dark '
    'background and marks the focused element with a bright outline or enlarged tile.')


def _clamp(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def describe(frame: np.ndarray, question: str | None = None,
             screens: list[str] | None = None) -> dict[str, Any] | None:
    '''Ask the fast vision model what is on screen. None if the LLM is unavailable/fails.'''
    ids = list(screens or [])
    prompt = (
        'Classify this PS5 screen. Return JSON with keys: '
        '"screen_id" (one of ' + json.dumps(ids + ['unknown']) + '), '
        '"description" (one or two sentences), '
        '"focused" (the UI element that has the highlight/focus outline, or ""), '
        '"text_visible" (list of prominent visible strings), '
        '"dialog" (bool: a modal dialog/popup is shown), '
        '"in_game" (bool: a game is rendering rather than system UI), '
        '"confidence" (0..1).')
    if question:
        prompt += ' Also add key "answer" answering: ' + question
    try:
        out = llm.ask(prompt, system=SYSTEM, frames=[frame], tier='fast', want_json=True)
    except llm.LLMUnavailable:
        return None
    except Exception:
        return None
    if not isinstance(out, dict):
        return None
    sid = str(out.get('screen_id') or 'unknown')
    out['screen_id'] = sid if sid in ids else 'unknown'
    out['description'] = str(out.get('description') or '')
    out['focused'] = str(out.get('focused') or '')
    tv = out.get('text_visible') or []
    out['text_visible'] = [str(t) for t in tv] if isinstance(tv, list) else [str(tv)]
    out['dialog'] = bool(out.get('dialog', False))
    out['in_game'] = bool(out.get('in_game', False))
    out['confidence'] = _clamp(out.get('confidence', 0.0))
    return out


def judge(frames_before_after: list[np.ndarray], claim: str) -> dict[str, Any] | None:
    '''Ask the strong model whether claim holds given [before, after] (or any) frames.'''
    prompt = (
        f'You are given {len(frames_before_after)} frame(s) in chronological order '
        '(first = before the action, last = after). Decide whether this claim holds for the '
        'final state: ' + json.dumps(claim) + '. Return JSON with keys "holds" (bool), '
        '"confidence" (0..1), "reason" (short).')
    try:
        out = llm.ask(prompt, system=SYSTEM, frames=list(frames_before_after), tier='strong',
                      want_json=True)
    except llm.LLMUnavailable:
        return None
    except Exception:
        return None
    if not isinstance(out, dict):
        return None
    return {'holds': bool(out.get('holds', False)), 'confidence': _clamp(out.get('confidence')),
            'reason': str(out.get('reason') or '')}
