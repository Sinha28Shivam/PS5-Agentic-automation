"""ActionGate: the single choke point every agent action passes through.

Enforces step limits, danger-screen and destructive-confirm rules, a dead-input
streak breaker and a send rate limit, and records before/after evidence.
"""

from __future__ import annotations

import re
import time
from typing import Any

import cv2
import numpy as np

from ..core.evidence import Evidence, frame_hash
from ..core.settings import get_settings
from ..core.state import Action, ActionRecord, Scenario, ScreenState
from ..hw.adapters import perform

DANGER_SCREENS = ("store", "account_prompt")
# Screens where ONLY these buttons may be sent (anything else could power off,
# restart or sign out the console). Matched by screen_id or extras['danger'].
LOCKDOWN = {"power_menu": ("circle",), "power": ("circle",),
            "home_customize": ("circle",), "layout": ("circle",)}
PS_HOLD_MAX = 1.0        # holding PS opens the quick/power menu
DESTRUCTIVE_PHRASES = ("delete", "initialize", "initialise", "factory", "reset to default",
                       "sign out", "format", "restore license", "restore licence")
_DESTRUCTIVE_RE = re.compile(r'\b(' + '|'.join(map(re.escape, DESTRUCTIVE_PHRASES)) + r')\b')
ESCAPE_BUTTONS = ("circle", "ps")
MIN_INTERVAL = 0.15


def _button(action: Action, *names: str) -> bool:
    return action.kind in ("press", "hold", "trigger") and action.name.lower() in names


def frame_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute grey-level difference on a 480x270 downscale."""
    def small(f: np.ndarray) -> np.ndarray:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
        return cv2.resize(g, (480, 270), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(small(a), small(b))))


class ActionGate:
    def __init__(self, rig: Any, evidence: Evidence, scenario: Scenario, settings: Any = None):
        self.rig = rig
        self.evidence = evidence
        self.scenario = scenario
        s = settings or get_settings()
        self.allow = {a.lower() for a in scenario.allow}
        self.max_steps = int(scenario.limits.get("max_steps") or s.get("runtime.max_steps", 40) or 40)
        self.dead_limit = int(s.get("runtime.dead_input_streak", 3) or 3)
        self.threshold = float(s.get("verification.screen_change_threshold", 0.5) or 0.5)
        self.notes: list[str] = []
        self._steps = 0
        self._dead = 0
        self._last_send = 0.0

    @property
    def steps(self) -> int:
        return self._steps

    @property
    def dead_streak(self) -> int:
        return self._dead

    def reset_streak(self) -> None:
        self._dead = 0

    def check(self, action: Action, screen: ScreenState, agent: str) -> tuple[bool, str]:
        if self._steps >= self.max_steps:
            return False, f"max_steps ({self.max_steps}) reached"
        if action.kind != "wait" and self._dead >= self.dead_limit:
            return False, "dead_input"
        escape = _button(action, *ESCAPE_BUTTONS)
        danger = screen.extras.get("danger")
        lock = LOCKDOWN.get(screen.screen_id) or LOCKDOWN.get(str(danger))
        if lock and "power" not in self.allow and not (
                action.kind == "wait" or _button(action, *lock)):
            return False, f"lockdown on {screen.screen_id or danger}: only {lock} allowed"
        if (_button(action, "ps") and action.kind == "hold"
                and (action.duration or 0) > PS_HOLD_MAX and "power" not in self.allow):
            return False, f"PS hold > {PS_HOLD_MAX}s opens the power menu"
        if (danger in DANGER_SCREENS and not escape and "store" not in self.allow
                and (action.kind == "type" or _button(action, "cross", "r2", "options"))):
            return False, f"danger screen ({danger}): {action.label()} not allowed"
        if _button(action, "cross") and "destructive" not in self.allow:
            texts = [action.reason.lower(), screen.focused.lower()]
            m = next((m for t in texts if t and (m := _DESTRUCTIVE_RE.search(t))), None)
            if m:
                return False, f"destructive confirm ({m.group(1)!r}) not allowed"
        if (screen.screen_id.startswith("settings") and _button(action, "cross")
                and "settings_write" not in self.allow):
            note = f"{agent}: cross on {screen.screen_id} may write a setting"
            self.notes.append(note)
            self.evidence.log("settings_write_warning", agent=agent, screen=screen.screen_id,
                              action=action.label(), focused=screen.focused)
        return True, "ok"

    def _save(self, frame: np.ndarray | None, tag: str) -> tuple[str | None, str | None]:
        if frame is None:
            return None, None
        return self.evidence.save_frame(frame, tag), frame_hash(frame)

    def _rate_limit(self) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last_send)
        if wait > 0:
            time.sleep(wait)
        self._last_send = time.monotonic()

    def execute(self, action: Action, screen: ScreenState, agent: str,
                settle: float | None = None) -> ActionRecord:
        label = action.label()
        before = self.rig.grab()
        rec = ActionRecord(action=action, agent=agent)
        rec.before_frame, rec.before_hash = self._save(before, f"{agent}-{label}-before")
        allowed, reason = self.check(action, screen, agent)
        if not allowed:
            rec.allowed, rec.blocked_reason = False, reason
            self.evidence.log("action_blocked", agent=agent, action=label, reason=reason,
                              screen=screen.screen_id, frame=rec.before_frame)
            return rec
        if action.kind != "wait":
            self._rate_limit()
        rec.sent_ok = bool(perform(self.rig, action))
        if settle is None:
            settle = {"type": 0.8, "wait": 0.0}.get(action.kind, 1.0)
        if settle > 0:
            time.sleep(settle)
        after = self.rig.grab()
        rec.after_frame, rec.after_hash = self._save(after, f"{agent}-{label}-after")
        if before is not None and after is not None:
            rec.delta = round(frame_delta(before, after), 3)
            rec.changed = rec.delta >= self.threshold
        self._steps += 1
        if action.kind not in ("wait", "type"):
            self._dead = 0 if rec.changed else self._dead + 1
        self.evidence.log("action", agent=agent, action=label, reason=action.reason,
                          sent_ok=rec.sent_ok, delta=rec.delta, changed=rec.changed,
                          before=rec.before_frame, after=rec.after_frame,
                          step=self._steps, dead_streak=self._dead)
        return rec
