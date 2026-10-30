'''Agent runtime: Ctx (non-serialisable services), observe/act helpers, prompts, LLM budget.

Agents are LangGraph nodes: `Agent.run(state, ctx)` returns a PARTIAL RunState update
(dict) that the graph merges. Lists in the update are always full new lists.
'''

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from ..core import llm
from ..core.evidence import Evidence
from ..core.settings import get_settings, load_yaml
from ..core.state import Action, ActionRecord, RunState, ScreenState, Step, Verdict
from ..perception import signatures
from ..perception.perceive import Perception

SETTLE_OVERRIDE: float | None = None     # tests set 0.0 to skip post-action settle sleeps
FATAL_DENIALS = ('dead_input', 'max_steps')


def load_game_profile(game: str | None, settings: Any = None) -> dict[str, Any] | None:
    if not game:
        return None
    s = settings or get_settings()
    path = Path(s.config_dir) / 'games' / game / 'profile.yaml'
    if not path.is_file():
        return None
    data = load_yaml(path)
    return data if isinstance(data, dict) else None


@dataclass
class Ctx:
    '''Runtime services shared by all agents (kept out of RunState: not serialisable).'''
    rig: Any
    gate: Any
    perception: Any
    evidence: Evidence
    settings: Any = None
    game_profile: dict[str, Any] | None = None
    last_frame: np.ndarray | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()

    @classmethod
    def build(cls, rig: Any, evidence: Evidence, scenario: Any, settings: Any = None,
              perception: Any = None) -> Ctx:
        from ..safety.action_gate import ActionGate
        s = settings or get_settings()
        return cls(rig=rig, gate=ActionGate(rig, evidence, scenario, s),
                   perception=perception or Perception(), evidence=evidence, settings=s,
                   game_profile=load_game_profile(scenario.game, s))


def limit(ctx: Ctx, state: RunState, key: str, settings_key: str, default: int) -> int:
    '''Scenario limit -> settings value -> default (0 is a valid value).'''
    v = state.scenario.limits.get(key)
    if v is None:
        v = ctx.settings.get(settings_key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def llm_ok(settings: Any = None) -> bool:
    '''LLM usable: API available AND the per-run call budget is not exhausted.'''
    if not llm.available():
        return False
    s = settings or get_settings()
    try:
        cap = int(s.get('llm.max_calls_per_run', 150) or 150)
    except (TypeError, ValueError):
        cap = 150
    return int(llm.snapshot_metrics().get('calls', 0)) < cap


def ask_llm(ctx: Ctx, prompt: str, **kw: Any) -> Any | None:
    '''llm.ask, or None when unavailable / over budget / failed.'''
    if not llm_ok(ctx.settings):
        return None
    try:
        return llm.ask(prompt, **kw)
    except Exception as exc:  # noqa: BLE001 - an LLM failure degrades to 'unavailable'
        ctx.evidence.log('llm_error', error=str(exc)[:300])
        return None


def load_prompt(name: str, settings: Any = None) -> str:
    s = settings or get_settings()
    path = Path(s.prompts_dir) / f'{name}.md'
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def load_frame(path: str | None) -> np.ndarray | None:
    if not path or not Path(path).is_file():
        return None
    return cv2.imread(path)


def observe(ctx: Ctx, state: RunState | None, tag: str,
            use_vision: str = 'auto') -> ScreenState:
    '''Grab a frame and perceive it (frame saved as evidence). Sets extras[danger].'''
    try:
        frame = ctx.rig.grab()
    except Exception as exc:  # noqa: BLE001 - capture failure == no evidence
        ctx.evidence.log('grab_error', error=str(exc)[:300])
        frame = None
    ctx.last_frame = frame
    if frame is None or getattr(frame, 'size', 0) == 0:
        return ScreenState(blank=True, extras={'no_frame': True, 'danger': None})
    mode = use_vision if llm_ok(ctx.settings) else 'never'
    screen = ctx.perception.observe(frame, evidence=ctx.evidence, use_vision=mode, tag=tag)
    if 'danger' not in screen.extras:
        screen.extras['danger'] = signatures.danger_screen(screen.text) if screen.text else None
    return screen


def act(ctx: Ctx, state: RunState, action: Action, agent: str, screen: ScreenState | None = None,
        settle: float | None = None, use_vision: str = 'auto') -> tuple[ActionRecord, ScreenState]:
    '''Execute through the ActionGate, then observe. Denied actions do not re-observe.'''
    current = screen if screen is not None else state.screen
    rec = ctx.gate.execute(action, current, agent, settle=SETTLE_OVERRIDE if settle is None else settle)
    if not rec.allowed:
        return rec, current
    return rec, observe(ctx, state, f'{agent}-{action.label()}', use_vision)


def is_fatal(rec: ActionRecord) -> bool:
    return not rec.allowed and rec.blocked_reason.startswith(FATAL_DENIALS)


def denial(rec: ActionRecord) -> dict[str, Any]:
    '''Routing for a gate denial: dead input / step budget -> BLOCKED, else recovery.'''
    if is_fatal(rec):
        return {'verdict': Verdict.BLOCKED, 'next_agent': 'reporter',
                'verdict_reason': f'{rec.agent}: {rec.action.label()} denied ({rec.blocked_reason})'}
    return {'next_agent': 'recovery'}


def copy_plan(state: RunState) -> list[Step]:
    return [s.model_copy(deep=True) for s in state.plan]


def screen_summary(screen: ScreenState, max_text: int = 600) -> dict[str, Any]:
    return {'screen_id': screen.screen_id, 'confidence': round(screen.confidence, 2),
            'source': screen.source, 'blank': screen.blank, 'text': screen.text[:max_text],
            'description': screen.description, 'focused': screen.focused,
            'danger': screen.extras.get('danger')}


def recent_actions(history: Iterable[ActionRecord], n: int = 8) -> list[str]:
    out = []
    for r in list(history)[-n:]:
        tail = f'DENIED({r.blocked_reason})' if not r.allowed else f'changed={r.changed}'
        out.append(f'{r.agent}:{r.action.label()} {tail}')
    return out


def update(state: RunState, ctx: Ctx, records: Iterable[ActionRecord] = (),
           notes: Iterable[str] = (), **kw: Any) -> dict[str, Any]:
    '''Partial RunState update with full (copied) history/notes lists.'''
    out: dict[str, Any] = {
        'history': list(state.history) + list(records),
        'notes': list(state.notes) + list(notes),
        'steps_taken': int(getattr(ctx.gate, 'steps', state.steps_taken)),
    }
    out.update(kw)
    return out


class Agent:
    name = 'agent'

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        raise NotImplementedError

    def __call__(self, state: RunState | dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        if isinstance(state, dict):
            state = RunState.model_validate(state)
        return self.run(state, ctx)

    def note(self, text: str) -> str:
        return f'[{self.name}] {text}'

    def log(self, ctx: Ctx, event: str, **data: Any) -> None:
        ctx.evidence.log(f'{self.name}.{event}', **data)
