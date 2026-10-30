'''Planner: scenario -> list[Step]. Explicit steps > hints > LLM (strong tier).

Shorthand actions (also used by hints, profiles and LLM replies):
  {macro: open_home}            {press: cross, times: 2, interval: 0.4}   {button: down}
  {type: 'astro bot'}           {hold: r2, duration: 1.5}                {wait: 2}
  {stick: left_stick, direction: right, duration: 0.3}                   {trigger: r2, value: 255}
  {combo: uppercut}  (game profile combo, expanded by GameplayAgent)
  {kind: press, name: cross, ...}  (full Action dict)   'press:cross' / 'macro:open_home' strings

Routing: next_agent = agent of the first PENDING step; 'reporter' (BLOCKED) when no plan.
'''

from __future__ import annotations

import json
from typing import Any

from ..core.state import Action, Expectation, RunState, Step, Verdict
from ..perception import signatures
from .base import Agent, Ctx, ask_llm, load_prompt, recent_actions, screen_summary, update

AGENTS = ('navigator', 'typist', 'gameplay', 'verifier', 'recovery')
_SHORT = ('macro', 'press', 'button', 'type', 'hold', 'wait', 'stick', 'trigger', 'combo')
_STEP_KEYS = ('id', 'goal', 'agent', 'actions', 'expect', 'max_attempts')
BUTTONS = {
    'cross': 'confirm/select (Home: open; keyboard: type focused key)',
    'circle': 'back/cancel (closes menus, Control Center, search, keyboard)',
    'square': 'keyboard backspace; nothing on Home',
    'triangle': 'Home: jump focus to Search icon; keyboard: space',
    'up/down/left/right': 'move focus (keyboard wraps left/right; never up from keyboard row 0)',
    'options': 'item options menu', 'ps': 'open Control Center (circle closes it)',
    'l1/r1': 'Home: switch Games/Media; keyboard: cursor left/right',
    'l2': 'keyboard shift', 'r2': 'keyboard Done -> focus first result (FORBIDDEN on store screens)',
}
MACROS = {'open_home': 'circle x3 back to Home (harmless on Home)',
          'open_search': 'from Home: triangle, cross, cross -> search keyboard open (focus g)',
          'submit_search': 'r2 Done -> focus first search result',
          'confirm': 'cross', 'go_back': 'circle',
          'home_from_game': 'from inside a game: Control Center -> Home icon (guarded) -> PS5 Home',
          'focus_tile:<title>[:ps4|ps5]': 'Home game row: walk until focused tile caption matches'}


def parse_action(d: Any) -> Action:
    '''Shorthand / full dict / 'kind:name' string -> Action. Raises ValueError if invalid.'''
    if isinstance(d, Action):
        return d.model_copy()
    if isinstance(d, str):
        kind, _, name = d.partition(':')
        d = {kind.strip(): name.strip()} if name else {'press': kind.strip()}
    if not isinstance(d, dict) or not d:
        raise ValueError(f'bad action: {d!r}')
    d = dict(d)
    extra = {k: d[k] for k in ('times', 'duration', 'interval', 'value', 'direction', 'reason')
             if d.get(k) is not None}
    if 'kind' in d:
        d = {k: v for k, v in d.items() if k in Action.model_fields and v is not None}
        if d.get('kind') == 'wait':
            dur = d.get('duration', d.get('name', d.get('value', 1.0)))
            try:
                dur = float(dur)
            except (TypeError, ValueError):
                dur = 1.0
            return Action(kind='wait', duration=dur, reason=str(d.get('reason', '')))
        if 'name' in d:
            d['name'] = str(d['name']).lower()
        if 'times' in d:
            d['times'] = int(d['times'])
        return Action(**d)
    key = next((k for k in _SHORT if k in d), None)
    if key is None:
        raise ValueError(f'unknown action shorthand: {d!r}')
    v = d[key]
    if key == 'type':
        return Action(kind='type', text=str(v), reason=str(d.get('reason', '')))
    if key == 'wait':
        return Action(kind='wait', duration=float(v if v is not None else extra.get('duration', 1.0)),
                      reason=str(d.get('reason', '')))
    if key == 'combo':
        return Action(kind='macro', name=f'combo:{v}', reason=str(d.get('reason', 'combo')))
    kind = 'press' if key == 'button' else key
    if kind == 'hold':
        extra.setdefault('duration', 1.0)
    if kind == 'stick':
        extra.setdefault('direction', 'right')
        extra.setdefault('duration', 0.5)
    extra['times'] = int(extra.get('times', 1))
    return Action(kind=kind, name=str(v).lower(), **extra)


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]


def parse_expect(d: Any) -> Expectation:
    if isinstance(d, Expectation):
        return d.model_copy()
    if not d:
        return Expectation()
    if isinstance(d, list):
        return merge_expectations(d)
    d = dict(d)
    return Expectation(screen=d.get('screen'), text_contains=_as_list(d.get('text_contains')),
                       text_absent=_as_list(d.get('text_absent')),
                       screen_changed=d.get('screen_changed'), vision=d.get('vision'),
                       hud=dict(d.get('hud') or {}))


def merge_expectations(items: list[Any]) -> Expectation:
    out = Expectation()
    claims: list[str] = []
    for it in items:
        e = parse_expect(it)
        out.screen = e.screen or out.screen
        out.text_contains += e.text_contains
        out.text_absent += e.text_absent
        if e.screen_changed is not None:
            out.screen_changed = e.screen_changed
        if e.vision:
            claims.append(e.vision)
        out.hud.update(e.hud)
    out.vision = ' AND '.join(claims) or None
    return out


def _default_agent(actions: list[Action]) -> str:
    if any(a.kind == 'type' for a in actions):
        return 'typist'
    if any(a.kind == 'macro' and a.name.startswith('combo:') for a in actions):
        return 'gameplay'
    return 'navigator'


def parse_step(d: Any, i: int) -> Step:
    '''Step dict (or bare action shorthand) -> Step. Raises ValueError if invalid.'''
    if isinstance(d, Step):
        return d.model_copy(deep=True)
    if not isinstance(d, dict):
        d = {'actions': [d]}
    d = dict(d)
    if 'actions' in d:
        raw = d.get('actions') or []
    else:
        own = {k: v for k, v in d.items() if k not in _STEP_KEYS}
        raw = [own] if any(k in own for k in _SHORT + ('kind',)) else []
    actions = [parse_action(a) for a in (raw if isinstance(raw, list) else [raw])]
    agent = str(d.get('agent') or _default_agent(actions))
    if agent not in AGENTS:
        raise ValueError(f'unknown agent {agent!r} in step {i}')
    goal = str(d.get('goal') or ', '.join(a.label() for a in actions) or f'step {i + 1}')
    return Step(id=str(d.get('id') or f's{i + 1}'), goal=goal, agent=agent, actions=actions,
                expect=parse_expect(d.get('expect')), max_attempts=int(d.get('max_attempts') or 8))


def _final_verify(state: RunState, i: int) -> Step | None:
    if not state.scenario.expect:
        return None
    return Step(id=f'verify{i + 1}', goal=f'Verify: {state.scenario.goal}', agent='verifier',
                expect=merge_expectations(state.scenario.expect), max_attempts=1)


def first_pending(plan: list[Step]) -> int:
    return next((i for i, s in enumerate(plan) if s.verdict == Verdict.PENDING), len(plan))


class PlannerAgent(Agent):
    name = 'planner'

    def deterministic(self, state: RunState, ctx: Ctx) -> tuple[list[Step], str] | None:
        sc = state.scenario
        if sc.steps:
            return [parse_step(d, i) for i, d in enumerate(sc.steps)], 'steps'
        if sc.hints:
            plan = [parse_step(d, i) for i, d in enumerate(sc.hints)]
            fin = _final_verify(state, len(plan))
            return plan + ([fin] if fin else []), 'hints'
        if sc.type in ('gameplay_scripted', 'gameplay_explore'):
            mode = 'explore' if sc.type == 'gameplay_explore' else 'scripted'
            combos = list((ctx.game_profile or {}).get('combos') or {})
            acts = [Action(kind='macro', name=f'combo:{c}', reason='combo') for c in combos] \
                if mode == 'scripted' else []
            plan = [Step(id='g1', goal=f'{mode}: {sc.goal}', agent='gameplay', actions=acts,
                         max_attempts=1)]
            fin = _final_verify(state, 1)
            return plan + ([fin] if fin else []), 'gameplay-default'
        return None

    def llm_plan(self, state: RunState, ctx: Ctx) -> list[Step] | None:
        payload: dict[str, Any] = {
            'scenario': {'id': state.scenario.id, 'goal': state.scenario.goal,
                         'type': state.scenario.type, 'game': state.scenario.game,
                         'expect': state.scenario.expect},
            'current_screen': screen_summary(state.screen),
            'known_screens': {k: {'description': v.description,
                                  'ocr_text_examples': (v.any_text + v.all_text)[:6],
                                  'transitions': v.transitions}
                              for k, v in sorted(signatures.load_screens().items())},
            'buttons': BUTTONS, 'macros': MACROS, 'agents': list(AGENTS),
        }
        if ctx.game_profile:
            payload['game_profile'] = {k: ctx.game_profile.get(k) for k in
                                       ('name', 'notes', 'combos', 'action_space', 'forbidden')
                                       if ctx.game_profile.get(k) is not None}
        if state.replans > 0:
            failed = state.current_step()
            payload['replan'] = {'attempt': state.replans,
                                 'failed_step': failed.model_dump(mode='json') if failed else None,
                                 'failure_reason': failed.reason if failed else state.verdict_reason,
                                 'history_tail': recent_actions(state.history, 12)}
        out = ask_llm(ctx, json.dumps(payload, default=str, indent=1),
                      system=load_prompt('planner', ctx.settings), tier='strong', max_tokens=2048)
        steps = out.get('steps') if isinstance(out, dict) else out if isinstance(out, list) else None
        if not steps:
            return None
        try:
            return [parse_step(d, i) for i, d in enumerate(steps)]
        except (ValueError, TypeError) as exc:
            self.log(ctx, 'bad_llm_plan', error=str(exc), reply=out)
            return None

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        notes: list[str] = []
        try:
            det = self.deterministic(state, ctx)
        except (ValueError, TypeError) as exc:
            return update(state, ctx, notes=[self.note(f'invalid scenario steps: {exc}')],
                          plan=[], verdict=Verdict.BLOCKED, next_agent='reporter',
                          verdict_reason=f'planner: invalid scenario steps/hints: {exc}')
        if det:
            plan, source = det
        else:
            plan, source = self.llm_plan(state, ctx) or [], 'llm'
        if not plan:
            why = 'no steps/hints and LLM planning unavailable or failed'
            return update(state, ctx, notes=[self.note(why)], plan=[], verdict=Verdict.BLOCKED,
                          verdict_reason=f'planner: {why}', next_agent='reporter')
        if state.replans > 0:
            prev = {s.id: s.attempts for s in state.plan}
            for s in plan:
                s.attempts = prev.get(s.id, 0)
            if source == 'llm':
                # Keep what was already proven (and the failure that triggered the
                # replan) so the report shows the full story; new steps follow.
                done = [s.model_copy(update={'id': f'r{state.replans - 1}-{s.id}'})
                        for s in state.plan if s.verdict.value != 'PENDING']
                for s in done:
                    if s.verdict.value == 'FAIL':
                        s.verdict = type(s.verdict)('SKIPPED')
                        s.reason = f'superseded by replan #{state.replans}: {s.reason}'
                for s in plan:
                    s.id = f'p{state.replans}-{s.id}'
                plan = done + plan
            notes.append(self.note(f'replan #{state.replans} ({source}): restarting plan'))
        cursor = first_pending(plan)
        notes.append(self.note(f'{len(plan)} steps from {source}: '
                               + ' | '.join(f'{s.id}:{s.agent}:{s.goal}' for s in plan)))
        self.log(ctx, 'plan', source=source, steps=[s.model_dump(mode='json') for s in plan])
        nxt = plan[cursor].agent if cursor < len(plan) else 'verifier'
        return update(state, ctx, notes=notes, plan=plan, cursor=cursor, next_agent=nxt)
