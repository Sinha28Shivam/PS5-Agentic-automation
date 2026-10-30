'''Recovery: get the console back to a known screen, then hand back for a replan.

Ladder (stops at the first rung that reaches a target screen):
  1. danger screen (store / account prompt) -> circle x2
  2. circle up to 3 times, observing after each, until 'home' or the step's expected screen
  3. macro open_home
  4. game scenarios: game profile 'recover' actions (shorthand list)
Then:
  - recoveries += 1; if recoveries > runtime.max_recoveries (default 3) -> BLOCKED, 'reporter'
  - gate dead_input / max_steps denial -> BLOCKED, 'reporter'
  - replans += 1; if replans <= max_replans -> 'planner' (it rebuilds the plan, keeping
    attempts), else the current step is marked FAIL and routed to 'verifier' (which finalises).
'''

from __future__ import annotations

from typing import Any

from ..core.state import Action, ActionRecord, RunState, ScreenState, Verdict
from .base import Agent, Ctx, act, copy_plan, denial, is_fatal, limit, observe, update
from .planner import parse_action

HOME = 'home'


class RecoveryAgent(Agent):
    name = 'recovery'

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        plan = copy_plan(state)
        step = plan[state.cursor] if 0 <= state.cursor < len(plan) else None
        recoveries = state.recoveries + 1
        max_rec = limit(ctx, state, 'max_recoveries', 'runtime.max_recoveries', 3)
        notes: list[str] = []
        if recoveries > max_rec:
            why = f'recovery budget exhausted ({recoveries - 1}/{max_rec})'
            if step is not None and step.verdict == Verdict.PENDING:
                step.verdict, step.reason = Verdict.BLOCKED, why
            return update(state, ctx, notes=[self.note(why)], plan=plan, recoveries=recoveries,
                          verdict=Verdict.BLOCKED, verdict_reason=why, next_agent='reporter')

        targets = {HOME} | ({step.expect.screen} if step and step.expect.screen else set())
        screen = observe(ctx, state, 'recovery-start')
        recs: list[ActionRecord] = []
        reached = screen.screen_id in targets

        def do(a: Action) -> ActionRecord:
            nonlocal screen, reached
            rec, screen = act(ctx, state, a, self.name, screen)
            recs.append(rec)
            reached = rec.allowed and screen.screen_id in targets
            return rec

        rungs: list[tuple[str, list[Action]]] = []
        if screen.screen_id == 'controller_user_select':
            # New GIMX session: PS5 asks which user owns the pad. Cross keeps the
            # focused (already logged-in) user - never "Add User".
            rungs.append(('user_select', [Action(kind='press', name='cross',
                                                 reason="confirm logged-in user")]))
        from ..perception.signatures import load_screens
        sdef = load_screens().get(screen.screen_id)
        if sdef and sdef.dismiss:
            rungs.append((f'dismiss:{screen.screen_id}',
                          [Action(kind='press', name=sdef.dismiss,
                                  reason=f'dismiss {screen.screen_id}')]))
        for d in (ctx.game_profile or {}).get('dialogs') or []:
            if d.get('answer') not in (None, 'wait') and d.get('text') and \
                    d['text'] in (screen.text or ''):
                rungs.append((f'dialog:{d["text"]}',
                              [Action(kind='press', name=str(d['answer']),
                                      reason=f'answer dialog {d["text"]!r}')]))
                break
        if screen.extras.get('danger'):
            rungs.append((f'danger:{screen.extras["danger"]}',
                          [Action(kind='press', name='circle', times=2, interval=0.6,
                                  reason='leave danger screen')]))
        rungs.append(('circle', [Action(kind='press', name='circle', reason='back out')
                                 for _ in range(3)]))
        rungs.append(('open_home', [Action(kind='macro', name='open_home', reason='recover home')]))
        # In-game, Circle never reaches the PS5 Home: go via the Control Center
        # (guarded: confirms only when the Home icon is visibly focused).
        rungs.append(('home_from_game', [Action(kind='macro', name='home_from_game',
                                                reason='recover home via Control Center')]))
        prof = (ctx.game_profile or {}).get('recover') if state.scenario.game else None
        if prof:
            try:
                rungs.append(('profile', [parse_action(d) for d in prof]))
            except (ValueError, TypeError) as exc:
                notes.append(self.note(f'bad profile recover actions: {exc}'))

        used: list[str] = []
        fatal: ActionRecord | None = None
        for label, actions in rungs:
            if reached:
                break
            used.append(label)
            for a in actions:
                rec = do(a)
                if is_fatal(rec):
                    fatal = rec
                    break
                if reached:
                    break
            if fatal:
                break
        self.log(ctx, 'ladder', rungs=used, reached=reached, screen=screen.screen_id)
        notes.append(self.note(f'ladder {used or ["none"]} -> screen {screen.screen_id!r} '
                               f'({"recovered" if reached else "target not reached"})'))
        base: dict[str, Any] = dict(plan=plan, screen=screen, recoveries=recoveries)
        if fatal:
            if step is not None and step.verdict == Verdict.PENDING:
                step.verdict, step.reason = Verdict.BLOCKED, f'recovery: {fatal.blocked_reason}'
            return update(state, ctx, recs, notes, **base, **denial(fatal))

        replans = state.replans + 1
        max_replans = limit(ctx, state, 'max_replans', 'runtime.max_replans', 1)
        if replans <= max_replans:
            if step is not None and step.verdict in (Verdict.FAIL, Verdict.BLOCKED):
                step.verdict = Verdict.PENDING
            return update(state, ctx, recs, notes, **base, replans=replans, next_agent='planner')
        if step is not None:
            step.verdict = Verdict.FAIL
            step.reason = step.reason or 'failed after recovery; replan budget exhausted'
        notes.append(self.note(f'replan budget exhausted ({state.replans}/{max_replans})'))
        return update(state, ctx, recs, notes, **base, next_agent='verifier')
