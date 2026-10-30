'''Navigator: drives the system/game UI towards the current step's goal.

Deterministic: step.actions run in order (one attempt). Otherwise an LLM loop (fast tier):
frame + goal + screen summary + recent actions -> {done, actions[<=3], reason}.

Routing: 'verifier' when actions ran / LLM says done / attempts exhausted;
'reporter' (verdict BLOCKED) on dead_input or max_steps denial, or when no LLM is
available for a goal-only step; 'recovery' on any other gate denial (e.g. danger screen).
'''

from __future__ import annotations

import json
from typing import Any

from ..core.state import Action, ActionRecord, RunState, ScreenState, Step, Verdict
from .base import (Agent, Ctx, act, ask_llm, copy_plan, denial, load_prompt, observe,
                   recent_actions, screen_summary, update)
from .planner import BUTTONS, MACROS, parse_action
from .verifier import check_expectation

MAX_PER_CALL = 3


class NavigatorAgent(Agent):
    name = 'navigator'

    def _quick(self, step: Step, screen: ScreenState) -> str:
        v, why = check_expectation(step.expect, None, screen, use_vision=False)
        return f'{v.value}: {why}'

    def _finish(self, state: RunState, ctx: Ctx, plan: list[Step], recs: list[ActionRecord],
                notes: list[str], screen: ScreenState, **kw: Any) -> dict[str, Any]:
        kw.setdefault('next_agent', 'verifier')
        return update(state, ctx, recs, notes, plan=plan, screen=screen, **kw)

    def run_actions(self, state: RunState, ctx: Ctx, step: Step, screen: ScreenState,
                    actions: list[Action]) -> tuple[list[ActionRecord], ScreenState, ActionRecord | None]:
        recs: list[ActionRecord] = []
        for a in actions:
            rec, screen = act(ctx, state, a, self.name, screen)
            recs.append(rec)
            if rec.after_frame:
                step.evidence.append(rec.after_frame)
            if not rec.allowed:
                return recs, screen, rec
        return recs, screen, None

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        plan = copy_plan(state)
        step = plan[state.cursor] if 0 <= state.cursor < len(plan) else None
        if step is None:
            return update(state, ctx, notes=[self.note('no current step')], next_agent='verifier')
        screen = state.screen if state.screen.frame_path else observe(ctx, state, f'nav-{step.id}')
        notes: list[str] = []
        if step.actions:
            step.attempts += 1
            recs, screen, denied = self.run_actions(state, ctx, step, screen, step.actions)
            if denied:
                notes.append(self.note(f'{step.id}: {denied.action.label()} denied: '
                                       f'{denied.blocked_reason}'))
                return self._finish(state, ctx, plan, recs, notes, screen, **denial(denied))
            notes.append(self.note(f'{step.id}: ran {len(recs)} actions; quick check '
                                   + self._quick(step, screen)))
            return self._finish(state, ctx, plan, recs, notes, screen)
        return self.llm_loop(state, ctx, plan, step, screen, notes)

    def llm_loop(self, state: RunState, ctx: Ctx, plan: list[Step], step: Step,
                 screen: ScreenState, notes: list[str]) -> dict[str, Any]:
        system = load_prompt('navigator', ctx.settings)
        recs: list[ActionRecord] = []
        while step.attempts < step.max_attempts:
            step.attempts += 1
            frames = [ctx.last_frame] if ctx.last_frame is not None else None
            payload = {'goal': step.goal, 'expect': step.expect.model_dump(mode='json'),
                       'screen': screen_summary(screen), 'attempt': step.attempts,
                       'max_attempts': step.max_attempts,
                       'recent_actions': recent_actions(list(state.history) + recs),
                       'buttons': BUTTONS, 'macros': MACROS}
            out = ask_llm(ctx, json.dumps(payload, default=str), system=system, frames=frames,
                          tier='fast', max_tokens=600)
            if not isinstance(out, dict):
                if not recs and step.attempts == 1:
                    step.verdict, step.reason = Verdict.BLOCKED, 'navigator needs the LLM (unavailable)'
                    notes.append(self.note(f'{step.id}: {step.reason}'))
                    return self._finish(state, ctx, plan, recs, notes, screen, next_agent='reporter',
                                        verdict=Verdict.BLOCKED,
                                        verdict_reason=f'{step.id}: {step.reason}')
                notes.append(self.note(f'{step.id}: LLM unavailable/invalid reply, handing to verifier'))
                break
            reason = str(out.get('reason') or '')
            if out.get('done'):
                notes.append(self.note(f'{step.id}: LLM done ({reason})'))
                break
            try:
                actions = [parse_action(a) for a in (out.get('actions') or [])][:MAX_PER_CALL]
            except (ValueError, TypeError) as exc:
                notes.append(self.note(f'{step.id}: bad LLM actions ({exc})'))
                continue
            for a in actions:
                a.reason = a.reason or reason
            new, screen, denied = self.run_actions(state, ctx, step, screen, actions)
            recs += new
            notes.append(self.note(f'{step.id} #{step.attempts}: '
                                   + ', '.join(a.label() for a in actions) + f' ({reason})'))
            if denied:
                notes.append(self.note(f'{step.id}: denied: {denied.blocked_reason}'))
                return self._finish(state, ctx, plan, recs, notes, screen, **denial(denied))
        return self._finish(state, ctx, plan, recs, notes, screen)
