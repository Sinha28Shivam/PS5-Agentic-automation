'''Preflight: prove the rig can see AND drive the console before any test step runs.

health = {ds4, session, capture, input}; each 'ok' | 'missing' | 'down' | 'blank' |
'no_frame' | 'unproven' | 'skipped' | 'error'.
Input probe (harmless, visible): scenario.setup actions (default {macro: open_home}),
then Triangle (on Home: focus jumps to the Search icon -> frame must change), then Down
to move focus back off it (accepted whether or not it changes). Skippable with
scenario.limits.skip_input_probe.

Routing: 'planner' when healthy; 'reporter' (verdict BLOCKED) otherwise.
'''

from __future__ import annotations

from typing import Any

from ..core.state import Action, ActionRecord, RunState, Verdict
from ..perception.perceive import is_blank
from .base import Agent, Ctx, act, observe, update
from .planner import parse_action


def _probe(fn: Any) -> bool | None:
    try:
        return bool(fn())
    except Exception:  # noqa: BLE001
        return None


class PreflightAgent(Agent):
    name = 'preflight'

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        health: dict[str, Any] = dict(state.health)
        notes: list[str] = []
        recs: list[ActionRecord] = []
        problems: list[str] = []

        ds4 = _probe(ctx.rig.ds4_present)
        health['ds4'] = 'ok' if ds4 else ('not_enumerated' if ds4 is False else 'error')
        if not ds4:
            # Observed on this rig: once GIMX claims the DS4 for auth pass-through
            # Windows can stop listing it, yet input is delivered. The input probe
            # below is the real proof, so this is a warning, not a blocker.
            notes.append(self.note('warning: DS4 not enumerated by Windows; relying on the '
                                   'input probe to prove delivery'))
        sess = _probe(ctx.rig.session_up)
        health['session'] = 'ok' if sess else ('down' if sess is False else 'error')
        if not sess:
            problems.append('GIMX session not up (start it and TAP PS on the DS4)')

        screen = observe(ctx, state, 'preflight', use_vision='never')
        frame = ctx.last_frame
        if frame is None:
            health['capture'] = 'no_frame'
            problems.append('capture returned no frame')
        elif screen.blank or is_blank(frame):
            health['capture'] = 'blank'
            problems.append('capture frame is blank (no signal / HDCP enabled?)')
        else:
            health['capture'] = 'ok'

        def out(**kw: Any) -> dict[str, Any]:
            return update(state, ctx, recs, notes, health=health, screen=screen, **kw)

        if problems:
            health['input'] = 'unproven'
            why = 'preflight: ' + '; '.join(problems)
            notes.append(self.note(why))
            self.log(ctx, 'blocked', health=health, problems=problems)
            return out(verdict=Verdict.BLOCKED, verdict_reason=why, next_agent='reporter')

        if state.scenario.limits.get('skip_input_probe'):
            health['input'] = 'skipped'
            notes.append(self.note('input probe skipped by scenario limits'))
            return out(next_agent='planner')

        try:
            setup = [parse_action(d) for d in state.scenario.setup] or \
                [Action(kind='macro', name='open_home', reason='preflight: known start screen')]
        except (ValueError, TypeError) as exc:
            why = f'preflight: invalid scenario setup: {exc}'
            notes.append(self.note(why))
            return out(verdict=Verdict.BLOCKED, verdict_reason=why, next_agent='reporter')
        for a in setup:
            rec, screen = act(ctx, state, a, self.name, screen, use_vision='never')
            recs.append(rec)
            if not rec.allowed:
                health['input'] = 'unproven'
                why = f'preflight: setup {a.label()} denied ({rec.blocked_reason})'
                notes.append(self.note(why))
                return out(verdict=Verdict.BLOCKED, verdict_reason=why, next_agent='reporter')

        # Probe 1: Triangle on Home moves focus to the Search icon (cheap, no overlay).
        # Probe 2 (fallback, works on ANY screen incl. in-game modals): PS opens the
        # Control Center overlay, Circle closes it. Either visible change proves delivery.
        probes = [('triangle', 'down'), ('ps', 'circle')]
        if screen.screen_id != 'home':
            probes.reverse()
        rec = None
        for press, undo in probes:
            rec, screen = act(ctx, state, Action(kind='press', name=press,
                                                 reason=f'input probe: {press}'),
                              self.name, screen, use_vision='never')
            recs.append(rec)
            if rec.allowed and rec.sent_ok and rec.changed:
                back, screen = act(ctx, state, Action(kind='press', name=undo,
                                                      reason=f'input probe: undo {press}'),
                                   self.name, screen, use_vision='never')
                recs.append(back)
                break
            ctx.gate.reset_streak()
        if not (rec and rec.allowed and rec.sent_ok and rec.changed):
            health['input'] = 'unproven'
            why = (f'preflight: input probe produced no visible change '
                   f'(last {rec.action.name if rec else "?"} delta={rec.delta if rec else None}). '
                   'Events are accepted but not delivered - DS4 auth (PS tap) missing?'
                   + ('' if ds4 else ' (DS4 is also not enumerated: re-wire it by USB)'))
            notes.append(self.note(why))
            self.log(ctx, 'blocked', health=health, delta=rec.delta if rec else None)
            return out(verdict=Verdict.BLOCKED, verdict_reason=why, next_agent='reporter')
        ctx.gate.reset_streak()
        health['input'] = 'ok'
        notes.append(self.note(f'healthy: ds4/session/capture ok, input proven '
                               f'({rec.action.name} delta={rec.delta})'))
        self.log(ctx, 'ok', health=health)
        return out(next_agent='planner')
