'''Typist: types text on the PS5 system keyboard and OCR-verifies it.

Assumes the keyboard is already open (planner puts {macro: open_search} first; non-type
actions in the step run in order around the typing). After typing, OCR reads the
typed-text region (controls.yaml text_entry.keyboard_layouts.<variant>.typed_text_region)
and compares case-insensitively ignoring spaces. On mismatch: Square (backspace) x N and
one retry. An unreadable region is noted, not failed - the verifier has the final say.

Routing: 'verifier' normally; 'reporter' (BLOCKED) on dead_input/max_steps denial;
'recovery' on other gate denials.
'''

from __future__ import annotations

import re
from typing import Any

from ..core.settings import load_yaml
from ..core.state import Action, ActionRecord, RunState, ScreenState, Step
from ..perception import ocr
from .base import Agent, Ctx, act, copy_plan, denial, observe, update

DEFAULT_REGION = {'x': 0.165, 'y': 0.11, 'width': 0.40, 'height': 0.06}
BACKSPACE_SLACK = 2


def squash(text: str) -> str:
    return re.sub(r'\s+', '', text or '').lower()


def typed_region(settings: Any) -> dict[str, float]:
    try:
        te = (load_yaml(settings.controls_config) or {}).get('text_entry') or {}
        variant = (te.get('defaults') or {}).get('keyboard_variant', 'ps5_system_en')
        region = ((te.get('keyboard_layouts') or {}).get(variant) or {}).get('typed_text_region')
        return dict(region) if region else dict(DEFAULT_REGION)
    except (OSError, AttributeError, TypeError):
        return dict(DEFAULT_REGION)


class TypistAgent(Agent):
    name = 'typist'

    def read_typed(self, ctx: Ctx) -> str | None:
        frame = ctx.last_frame
        if frame is None:
            return None
        try:
            return ocr.read_text(frame, typed_region(ctx.settings))
        except Exception as exc:  # noqa: BLE001 - OCR engine missing etc.
            self.log(ctx, 'ocr_error', error=str(exc)[:200])
            return None

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        plan = copy_plan(state)
        step: Step | None = plan[state.cursor] if 0 <= state.cursor < len(plan) else None
        if step is None:
            return update(state, ctx, notes=[self.note('no current step')], next_agent='verifier')
        step.attempts += 1
        screen: ScreenState = state.screen
        recs: list[ActionRecord] = []
        notes: list[str] = []

        def run(a: Action) -> ActionRecord:
            nonlocal screen
            rec, screen = act(ctx, state, a, self.name, screen)
            recs.append(rec)
            if rec.after_frame:
                step.evidence.append(rec.after_frame)
            return rec

        def out(**kw: Any) -> dict[str, Any]:
            kw.setdefault('next_agent', 'verifier')
            return update(state, ctx, recs, notes, plan=plan, screen=screen, **kw)

        if not any(a.kind == 'type' for a in step.actions):
            notes.append(self.note(f'{step.id}: no type action in step'))
        for a in step.actions:
            rec = run(a)
            if not rec.allowed:
                notes.append(self.note(f'{step.id}: {a.label()} denied: {rec.blocked_reason}'))
                return out(**denial(rec))
            if a.kind != 'type':
                continue
            want = squash(a.text or '')
            got = self.read_typed(ctx)
            if got is None or not squash(got):
                notes.append(self.note(f'{step.id}: typed {a.text!r}; OCR could not read the field'))
                continue
            if squash(got) == want or want in squash(got):
                notes.append(self.note(f'{step.id}: typed {a.text!r} verified (ocr={got!r})'))
                continue
            n = len(squash(got)) + BACKSPACE_SLACK
            notes.append(self.note(f'{step.id}: typed mismatch ocr={got!r} want={a.text!r}; '
                                   f'backspace x{n} and retry'))
            for b in (Action(kind='press', name='square', times=n, interval=0.15,
                             reason='clear mistyped text'), a.model_copy()):
                if b.kind == 'type':
                    ctx.rig.reset_keyboard()
                rec = run(b)
                if not rec.allowed:
                    notes.append(self.note(f'{step.id}: retry denied: {rec.blocked_reason}'))
                    return out(**denial(rec))
            got2 = self.read_typed(ctx)
            ok = got2 is not None and want in squash(got2)
            notes.append(self.note(f'{step.id}: retry ocr={got2!r} -> {"ok" if ok else "still mismatched"}'))
            step.reason = '' if ok else f'typed text mismatch: ocr={got2!r} want={a.text!r}'
        return out()
