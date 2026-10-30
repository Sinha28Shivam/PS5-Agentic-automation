'''Gameplay: drives a running game (PS4-compatible build via DS4 emulation).

Modes (step goal prefix 'explore'/'scripted', else scenario.type):
  scripted - runs step.actions; {combo: name} / macro 'combo:<name>' expand from
             profile['combos'][name] (shorthand list). HUD change is measured on
             profile['hud'] regions ({name: {x,y,width,height}} fractions): per-region mean
             abs grey diff before vs after -> metrics['gameplay']['hud'].
  explore  - for explore_seconds (step/limits, default 60), each tick (gameplay.tick_seconds,
             default 1.5): frame -> LLM (fast) picks a name from profile['action_space'];
             its shorthand sequence runs through the gate. Stops on round_over / menu /
             LLM budget. No LLM -> seeded random policy (noted). gate.reset_streak() every
             tick: fights always animate, so dead-input is not meaningful here.
metrics['gameplay'] = {mode, counts{name: n}, ticks, policy, hud, stopped}.

Routing: 'verifier'; 'reporter' (BLOCKED) on max_steps denial or no frames;
'recovery' on other denials (e.g. a danger/store screen).
'''

from __future__ import annotations

import json
import random
import time
from typing import Any

import cv2
import numpy as np

from ..core.state import Action, ActionRecord, RunState, ScreenState, Step, Verdict
from ..perception.hud import read_hud
from ..perception.ocr import crop
from .base import (Agent, Ctx, act, ask_llm, copy_plan, denial, load_prompt, observe,
                   screen_summary, update)
from .planner import parse_action

CLOCK = time.monotonic
SLEEP = time.sleep
DEFAULT_ACTION_SPACE: dict[str, list[dict[str, Any]]] = {
    'idle': [{'wait': 0.3}],
    'walk_forward': [{'stick': 'left_stick', 'direction': 'right', 'duration': 0.4}],
    'walk_back': [{'stick': 'left_stick', 'direction': 'left', 'duration': 0.4}],
    'punch': [{'press': 'square'}], 'kick': [{'press': 'cross'}],
    'block': [{'hold': 'r2', 'duration': 0.6}],
}


def hud_diff(before: np.ndarray | None, after: np.ndarray | None,
             regions: dict[str, dict[str, float]]) -> dict[str, float]:
    '''Mean abs grey diff per fractional region (frames resized to a common size).'''
    if before is None or after is None or not regions:
        return {}
    if before.shape[:2] != after.shape[:2]:
        after = cv2.resize(after, (before.shape[1], before.shape[0]))
    g = lambda f: cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
    out: dict[str, float] = {}
    for name, reg in regions.items():
        a, b = crop(g(before), reg), crop(g(after), reg)
        out[name] = round(float(cv2.absdiff(a, b).mean()), 3) if a.size and b.size else 0.0
    return out


def expand_move(name: str, profile: dict[str, Any] | None, depth: int = 0) -> list[dict[str, Any]]:
    """Resolve a move/combo name to shorthand steps. Combos may list move names."""
    prof = profile or {}
    moves, combos = prof.get('moves') or {}, prof.get('combos') or {}
    seq = moves.get(name) if name in moves else combos.get(name)
    if seq is None or depth > 4:
        return [{'press': name}]
    out: list[dict[str, Any]] = []
    for item in seq:
        if isinstance(item, str):
            out += expand_move(item, profile, depth + 1)
        else:
            out.append(item)
    return out


def action_space(profile: dict[str, Any] | None) -> dict[str, list[Action]]:
    raw = (profile or {}).get('action_space') or DEFAULT_ACTION_SPACE
    if isinstance(raw, list):
        raw = {n: expand_move(n, profile) for n in raw}
    return {str(k): [parse_action(a) for a in (v if isinstance(v, list) else [v])]
            for k, v in raw.items()}


class GameplayAgent(Agent):
    name = 'gameplay'

    def __init__(self, seed: int = 1234):
        self.seed = seed

    @staticmethod
    def mode(step: Step, state: RunState) -> str:
        g = step.goal.lower()
        if g.startswith('explore') or (state.scenario.type == 'gameplay_explore'
                                       and not g.startswith('scripted')):
            return 'explore'
        return 'scripted'

    def expand(self, a: Action, profile: dict[str, Any] | None) -> list[Action]:
        if a.kind == 'macro' and a.name.startswith('combo:'):
            name = a.name.split(':', 1)[1]
            prof = profile or {}
            if name not in (prof.get('combos') or {}) and name not in (prof.get('moves') or {}):
                raise ValueError(f'combo {name!r} not in game profile')
            return [parse_action(x).model_copy(update={'reason': f'combo {name}'})
                    for x in expand_move(name, prof)]
        return [a]

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        plan = copy_plan(state)
        step = plan[state.cursor] if 0 <= state.cursor < len(plan) else None
        if step is None:
            return update(state, ctx, notes=[self.note('no current step')], next_agent='verifier')
        step.attempts += 1
        mode = self.mode(step, state)
        metrics = dict(state.metrics)
        gm: dict[str, Any] = {'mode': mode, 'counts': {}, 'ticks': 0, 'policy': 'scripted',
                              'hud': {}, 'stopped': ''}
        screen = observe(ctx, state, f'game-{step.id}-start', use_vision='never')
        start = ctx.last_frame
        if start is None:
            step.verdict, step.reason = Verdict.BLOCKED, 'no frame from capture'
            return update(state, ctx, notes=[self.note(step.reason)], plan=plan, screen=screen,
                          verdict=Verdict.BLOCKED, verdict_reason=f'{step.id}: {step.reason}',
                          next_agent='reporter')
        profile = ctx.game_profile or {}
        gm['hud_before'] = self.hud_read(ctx, profile)
        fn = self.explore if mode == 'explore' else self.scripted
        recs, notes, screen, route = fn(state, ctx, step, screen, gm)
        SLEEP(float(profile.get('hud_settle', 1.0)))
        gm['hud_after'] = self.hud_read(ctx, profile)
        regions = {k: v for k, v in (profile.get('hud') or {}).items()
                   if isinstance(v, dict) and {'x', 'y', 'width', 'height'} <= set(v)}
        gm['hud'] = hud_diff(start, ctx.last_frame, regions)
        metrics['gameplay'] = gm
        notes.append(self.note(f'{step.id} {mode}: counts={gm["counts"]} hud={gm["hud"]} '
                               f'policy={gm["policy"]} {gm["stopped"]}'))
        self.log(ctx, 'summary', step=step.id, **gm)
        route.setdefault('next_agent', 'verifier')
        return update(state, ctx, recs, notes, plan=plan, screen=screen, metrics=metrics, **route)

    @staticmethod
    def hud_read(ctx: Ctx, profile: dict[str, Any], n: int = 3) -> dict[str, float]:
        """Median of n fresh HUD reads (robust to a fighter briefly covering a bar)."""
        if not profile.get('hud'):
            return {}
        reads = []
        for _ in range(n):
            f = ctx.rig.grab()
            if f is not None:
                reads.append(read_hud(f, profile))
            SLEEP(0.08)
        if not reads:
            return {}
        return {k: round(float(np.median([r[k] for r in reads])), 3) for k in reads[0]}

    def _exec(self, state: RunState, ctx: Ctx, step: Step, screen: ScreenState, name: str,
              actions: list[Action], recs: list[ActionRecord], gm: dict[str, Any]
              ) -> tuple[ScreenState, ActionRecord | None]:
        gm['counts'][name] = gm['counts'].get(name, 0) + 1
        for a in actions:
            ctx.gate.reset_streak()
            rec, screen = act(ctx, state, a, self.name, screen, settle=0.1, use_vision='never')
            recs.append(rec)
            if not rec.allowed:
                return screen, rec
        if recs and recs[-1].after_frame:
            step.evidence.append(recs[-1].after_frame)
        return screen, None

    def scripted(self, state: RunState, ctx: Ctx, step: Step, screen: ScreenState,
                 gm: dict[str, Any]) -> tuple[list[ActionRecord], list[str], ScreenState, dict]:
        recs: list[ActionRecord] = []
        notes: list[str] = []
        for a in step.actions:
            try:
                seq = self.expand(a, ctx.game_profile)
            except ValueError as exc:
                step.verdict, step.reason = Verdict.BLOCKED, str(exc)
                return recs, [self.note(str(exc))], screen, {
                    'verdict': Verdict.BLOCKED, 'verdict_reason': f'{step.id}: {exc}',
                    'next_agent': 'reporter'}
            name = a.name.split(':', 1)[1] if a.name.startswith('combo:') else a.label()
            screen, denied = self._exec(state, ctx, step, screen, name, seq, recs, gm)
            if denied:
                notes.append(self.note(f'{name}: denied ({denied.blocked_reason})'))
                return recs, notes, screen, denial(denied)
        if not step.actions:
            notes.append(self.note(f'{step.id}: scripted step has no actions'))
        return recs, notes, screen, {}

    def explore(self, state: RunState, ctx: Ctx, step: Step, screen: ScreenState,
                gm: dict[str, Any]) -> tuple[list[ActionRecord], list[str], ScreenState, dict]:
        recs: list[ActionRecord] = []
        notes: list[str] = []
        space = action_space(ctx.game_profile)
        names = list(space)
        seconds = float(state.scenario.limits.get('explore_seconds', 60))
        tick = float(ctx.settings.get('gameplay.tick_seconds', 1.5) or 1.5)
        max_ticks = int(state.scenario.limits.get('explore_ticks') or 0)
        system = load_prompt('gameplay', ctx.settings)
        rng = random.Random(self.seed)
        deadline = CLOCK() + seconds
        while CLOCK() < deadline and (not max_ticks or gm['ticks'] < max_ticks):
            t0 = CLOCK()
            gm['ticks'] += 1
            ctx.gate.reset_streak()
            if gm['ticks'] > 1:
                screen = observe(ctx, state, f'game-{step.id}-t{gm["ticks"]}', use_vision='never')
            out = None
            if gm['policy'] != 'random':
                frames = [ctx.last_frame] if ctx.last_frame is not None else None
                payload = {'goal': step.goal, 'tick': gm['ticks'], 'action_space': names,
                           'screen': screen_summary(screen, 300),
                           'counts': gm['counts'], 'game': (ctx.game_profile or {}).get('name')}
                out = ask_llm(ctx, json.dumps(payload, default=str), system=system, frames=frames,
                              tier='fast', max_tokens=300)
            if isinstance(out, dict):
                gm['policy'] = 'llm'
                sit = out.get('situation') or {}
                if sit.get('round_over') or sit.get('menu'):
                    gm['stopped'] = 'round_over' if sit.get('round_over') else 'menu'
                    break
                name = str(out.get('action') or '')
                if name not in space:
                    notes.append(self.note(f'LLM chose unknown action {name!r}; idling'))
                    name = 'idle' if 'idle' in space else names[0]
            else:
                if gm['policy'] == 'llm':
                    gm['stopped'] = 'llm budget/unavailable'
                    break
                if gm['policy'] != 'random':
                    notes.append(self.note('LLM unavailable: seeded random policy over action_space'))
                gm['policy'] = 'random'
                name = rng.choice(names)
            screen, denied = self._exec(state, ctx, step, screen, name,
                                        [a.model_copy() for a in space[name]], recs, gm)
            if denied:
                notes.append(self.note(f'{name}: denied ({denied.blocked_reason})'))
                gm['stopped'] = f'denied: {denied.blocked_reason}'
                return recs, notes, screen, denial(denied)
            rest = tick - (CLOCK() - t0)
            if rest > 0 and CLOCK() + rest < deadline:
                SLEEP(rest)
        gm['stopped'] = gm['stopped'] or 'time/tick budget'
        return recs, notes, screen, {}
