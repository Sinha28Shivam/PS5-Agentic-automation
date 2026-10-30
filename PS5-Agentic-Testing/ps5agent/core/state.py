"""Shared data contracts. Every agent reads/writes these - keep them stable."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"        # could not be judged (no evidence, hardware, safety)
    SKIPPED = "SKIPPED"
    PENDING = "PENDING"


class ScreenState(BaseModel):
    """What Perception says the console is showing."""
    frame_path: str | None = None
    frame_hash: str | None = None
    screen_id: str = "unknown"            # id from config/screens/*.yaml or "unknown"
    confidence: float = 0.0
    source: Literal["signature", "vision", "none"] = "none"
    text: str = ""                        # OCR text, lower-cased
    blank: bool = False
    description: str = ""                 # vision summary (if vision was used)
    focused: str = ""                     # what has focus, if known
    extras: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)


class Action(BaseModel):
    """One controller action. kind: press|hold|macro|type|stick|trigger|wait."""
    kind: Literal["press", "hold", "macro", "type", "stick", "trigger", "wait"]
    name: str = ""                        # button / macro / stick name
    times: int = 1
    duration: float | None = None
    text: str | None = None               # for kind=type
    direction: str | None = None          # for kind=stick
    value: int | None = None              # for kind=trigger
    interval: float | None = None
    reason: str = ""                      # why the agent chose it (logged)

    def label(self) -> str:
        if self.kind == "type":
            return f"type({self.text!r})"
        if self.kind == "wait":
            return f"wait({self.duration}s)"
        base = f"{self.kind}:{self.name}"
        if self.direction:
            base += f":{self.direction}"
        if self.times > 1:
            base += f"x{self.times}"
        return base


class ActionRecord(BaseModel):
    action: Action
    agent: str
    allowed: bool = True
    blocked_reason: str = ""
    sent_ok: bool = False
    before_hash: str | None = None
    after_hash: str | None = None
    before_frame: str | None = None
    after_frame: str | None = None
    delta: float | None = None            # mean abs pixel diff before->after
    changed: bool | None = None
    ts: float = Field(default_factory=time.time)


class Expectation(BaseModel):
    """What must be true after a step. Any provided field must hold."""
    screen: str | None = None             # screen_id
    text_contains: list[str] = Field(default_factory=list)
    text_absent: list[str] = Field(default_factory=list)
    screen_changed: bool | None = None
    vision: str | None = None             # free-text claim judged by vision LLM
    # Game HUD checks against metrics['gameplay']['hud_before'/'hud_after'] (perception.hud):
    #   {"in_fight": true, "p2_health_drop_min": 0.02, "p1_health_min": 0.0}
    hud: dict[str, Any] = Field(default_factory=dict)


class Step(BaseModel):
    """A planned sub-goal."""
    id: str
    goal: str
    agent: Literal["navigator", "typist", "gameplay", "verifier", "recovery"] = "navigator"
    actions: list[Action] = Field(default_factory=list)   # deterministic hints
    expect: Expectation = Field(default_factory=Expectation)
    max_attempts: int = 8
    attempts: int = 0
    verdict: Verdict = Verdict.PENDING
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)     # frame paths


class Scenario(BaseModel):
    id: str
    goal: str
    type: Literal["system_ui", "game_menu", "gameplay_scripted",
                  "gameplay_explore", "soak"] = "system_ui"
    game: str | None = None
    hints: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)  # optional explicit steps
    expect: list[dict[str, Any]] = Field(default_factory=list)
    setup: list[dict[str, Any]] = Field(default_factory=list)  # e.g. [{macro: open_home}]
    teardown: list[dict[str, Any]] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)  # ActionGate exceptions, e.g. ["settings_write"]


class RunState(BaseModel):
    """LangGraph state. Agents return partial dicts that are merged in."""
    run_id: str
    scenario: Scenario
    run_dir: str
    plan: list[Step] = Field(default_factory=list)
    cursor: int = 0                       # index of current step
    screen: ScreenState = Field(default_factory=ScreenState)
    history: list[ActionRecord] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)       # agent log lines
    replans: int = 0
    recoveries: int = 0
    steps_taken: int = 0
    next_agent: str = "preflight"
    verdict: Verdict = Verdict.PENDING
    verdict_reason: str = ""
    health: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)  # llm calls, tokens, timings
    started: float = Field(default_factory=time.time)
    finished: float | None = None

    def current_step(self) -> Step | None:
        return self.plan[self.cursor] if 0 <= self.cursor < len(self.plan) else None
