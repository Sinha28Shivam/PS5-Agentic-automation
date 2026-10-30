'''Verifier: judges the current step's Expectation against fresh visual evidence.

Rules: no frame / blank frame -> BLOCKED. Deterministic checks (screen id, text, change)
run first; any miss -> FAIL. A vision claim needs the LLM - unavailable -> BLOCKED.
Never PASS without a saved frame.

Routing:
  PASS  -> next PENDING step's agent, or 'reporter' when the plan is done
  FAIL  -> 'recovery' while step.attempts < max_attempts and replans < max_replans,
           otherwise the run ends: 'reporter'
  BLOCKED, or a step pre-marked FAIL/BLOCKED by another agent -> 'reporter'
When the run ends, remaining PENDING steps become SKIPPED and the overall verdict is
BLOCKED if any step BLOCKED, else FAIL if any FAIL, else PASS (needs >= 1 PASS).
'''

from __future__ import annotations

from typing import Any

import numpy as np

from ..core.state import ActionRecord, Expectation, RunState, ScreenState, Step, Verdict
from ..perception import signatures, vision
from ..perception.perceive import delta as frame_delta
from .base import Agent, Ctx, copy_plan, limit, llm_ok, load_frame, observe, update


def _empty(exp: Expectation) -> bool:
    return not (exp.screen or exp.text_contains or exp.text_absent
                or exp.screen_changed is not None or exp.vision or exp.hud)


def check_hud(exp: dict[str, Any], gm: dict[str, Any]) -> tuple[Verdict, str] | None:
    """HUD expectations vs gameplay metrics. None = no hud expectation."""
    if not exp:
        return None
    before, after = gm.get('hud_before') or {}, gm.get('hud_after') or {}
    if not after:
        return Verdict.BLOCKED, 'hud expectation but no HUD reading (no game profile hud?)'
    if exp.get('in_fight') and not (before.get('in_fight') or after.get('in_fight')):
        return Verdict.BLOCKED, f'not in a fight (hud before={before} after={after})'
    out: list[str] = []
    for key, want in exp.items():
        if key.endswith('_drop_min'):
            bar = key[:-len('_drop_min')]
            if bar not in before or bar not in after:
                return Verdict.BLOCKED, f'{bar} not readable'
            drop = round(before[bar] - after[bar], 3)
            if drop < float(want):
                return Verdict.FAIL, f'{bar} dropped {drop} < {want} (before {before[bar]} after {after[bar]})'
            out.append(f'{bar} -{drop}')
        elif key.endswith('_min') and key[:-4] in after:
            if after[key[:-4]] < float(want):
                return Verdict.FAIL, f'{key[:-4]}={after[key[:-4]]} < {want}'
    return Verdict.PASS, 'hud ' + (', '.join(out) or 'ok')


def _haystack(s: ScreenState) -> str:
    v = s.extras.get('vision') or {}
    extra = ' '.join(str(t) for t in (v.get('text_visible') or [])) if isinstance(v, dict) else ''
    return ' '.join(x for x in (s.text, extra, s.focused) if x)


def _changed(before: ScreenState | None, after: ScreenState, frames: list[np.ndarray],
             last: ActionRecord | None, threshold: float) -> tuple[bool | None, str]:
    if last is not None and last.changed is not None:
        return bool(last.changed), f'last action delta={last.delta}'
    if len(frames) >= 2:
        d = frame_delta(frames[0], frames[-1])
        return d >= threshold, f'frame delta={d:.3f}'
    if before is not None and before.frame_hash and after.frame_hash:
        return before.frame_hash != after.frame_hash, 'frame hash comparison'
    return None, 'no before/after evidence'


def check_expectation(exp: Expectation, before: ScreenState | None, after: ScreenState,
                      frames: list[np.ndarray] | None = None, *, last: ActionRecord | None = None,
                      use_vision: bool = True, threshold: float = 0.5,
                      gm: dict[str, Any] | None = None) -> tuple[Verdict, str]:
    '''Judge an Expectation. frames = [before?, ..., after] for change/vision checks.'''
    frames = [f for f in (frames or []) if f is not None]
    if not after.frame_path:
        return Verdict.BLOCKED, 'no frame captured - cannot verify'
    if after.blank:
        return Verdict.BLOCKED, 'blank frame (no signal / HDCP) - cannot verify'
    if _empty(exp):
        return Verdict.PASS, 'no expectation; frame captured'
    passed: list[str] = []
    if exp.screen:
        if after.screen_id != exp.screen:
            return Verdict.FAIL, (f'screen is {after.screen_id!r} (conf {after.confidence:.2f}), '
                                  f'expected {exp.screen!r}')
        passed.append(f'screen={exp.screen}')
    text = _haystack(after)
    missing = [p for p in exp.text_contains if not signatures.fuzzy_contains(text, p)]
    if missing:
        return Verdict.FAIL, f'text not found: {missing}'
    if exp.text_contains:
        passed.append(f'text {exp.text_contains}')
    present = [p for p in exp.text_absent if signatures.fuzzy_contains(text, p)]
    if present:
        return Verdict.FAIL, f'text should be absent but found: {present}'
    if exp.screen_changed is not None:
        ch, how = _changed(before, after, frames, last, threshold)
        if ch is None:
            return Verdict.BLOCKED, f'screen_changed: {how}'
        if ch != exp.screen_changed:
            return Verdict.FAIL, f'screen_changed={ch}, expected {exp.screen_changed} ({how})'
        passed.append(f'screen_changed={ch} ({how})')
    if exp.hud:
        hv = check_hud(exp.hud, gm or {})
        if hv and hv[0] != Verdict.PASS:
            return hv
        if hv:
            passed.append(hv[1])
    if exp.vision:
        if not use_vision:
            return Verdict.PENDING, 'vision claim not yet judged'
        if not llm_ok() or not frames:
            return Verdict.BLOCKED, f'vision claim {exp.vision!r} needs the LLM (unavailable)'
        j = vision.judge(frames[-2:] if len(frames) >= 2 else frames, exp.vision)
        if j is None:
            return Verdict.BLOCKED, f'vision judge failed for {exp.vision!r}'
        if not j['holds']:
            return Verdict.FAIL, f'vision: claim does not hold ({j["reason"]})'
        passed.append(f'vision ok ({j["confidence"]:.2f}: {j["reason"]})')
    return Verdict.PASS, '; '.join(passed)


def finalize(plan: list[Step]) -> tuple[Verdict, str]:
    '''Overall verdict; PENDING steps are marked SKIPPED in place.'''
    for s in plan:
        if s.verdict == Verdict.PENDING:
            s.verdict, s.reason = Verdict.SKIPPED, s.reason or 'not reached'
    bad = [s for s in plan if s.verdict == Verdict.BLOCKED]
    if bad:
        return Verdict.BLOCKED, f'step {bad[0].id} BLOCKED: {bad[0].reason}'
    bad = [s for s in plan if s.verdict == Verdict.FAIL]
    if bad:
        return Verdict.FAIL, f'step {bad[0].id} FAILED: {bad[0].reason}'
    if not any(s.verdict == Verdict.PASS for s in plan):
        return Verdict.BLOCKED, 'no step passed with evidence'
    return Verdict.PASS, f'all {sum(s.verdict == Verdict.PASS for s in plan)} steps passed'


class VerifierAgent(Agent):
    name = 'verifier'

    def _done(self, state: RunState, ctx: Ctx, plan: list[Step], notes: list[str],
              **kw: Any) -> dict[str, Any]:
        verdict, reason = finalize(plan)
        notes.append(self.note(f'overall {verdict.value}: {reason}'))
        self.log(ctx, 'final', verdict=verdict.value, reason=reason)
        return update(state, ctx, notes=notes, plan=plan, verdict=verdict, verdict_reason=reason,
                      next_agent='reporter', **kw)

    def run(self, state: RunState, ctx: Ctx) -> dict[str, Any]:
        plan = copy_plan(state)
        notes: list[str] = []
        cur = state.cursor
        step = plan[cur] if 0 <= cur < len(plan) else None
        if step is None:
            return self._done(state, ctx, plan, notes)
        if step.verdict != Verdict.PENDING:
            notes.append(self.note(f'{step.id} already {step.verdict.value}: {step.reason}'))
            return self._done(state, ctx, plan, notes)
        if step.agent == 'verifier':
            step.attempts += 1
        after = observe(ctx, state, f'verify-{step.id}', use_vision='auto')
        last = state.history[-1] if state.history and state.history[-1].allowed else None
        frames = [load_frame(last.before_frame) if last else None, ctx.last_frame]
        threshold = float(ctx.settings.get('verification.screen_change_threshold', 0.5) or 0.5)
        gm = dict((state.metrics or {}).get('gameplay') or {})
        if step.expect.hud and ctx.game_profile and (step.agent != 'gameplay'
                                                     or not gm.get('hud_after')):
            # Non-gameplay step with a HUD expectation: read the HUD now (median of 3).
            from .gameplay import GameplayAgent
            gm = {'hud_before': {}, 'hud_after': GameplayAgent.hud_read(ctx, ctx.game_profile)}
        verdict, reason = check_expectation(step.expect, None, after, frames, last=last,
                                            threshold=threshold, gm=gm)
        step.reason = reason
        if after.frame_path:
            step.evidence = list(step.evidence) + [after.frame_path]
        notes.append(self.note(f'{step.id} {verdict.value}: {reason}'))
        self.log(ctx, 'step', step=step.id, verdict=verdict.value, reason=reason,
                 frame=after.frame_path, attempts=step.attempts)
        if verdict == Verdict.PASS:
            step.verdict = Verdict.PASS
            nxt = next((i for i in range(cur + 1, len(plan))
                        if plan[i].verdict == Verdict.PENDING), len(plan))
            if nxt >= len(plan):
                return self._done(state, ctx, plan, notes, cursor=nxt, screen=after)
            return update(state, ctx, notes=notes, plan=plan, cursor=nxt, screen=after,
                          next_agent=plan[nxt].agent)
        step.verdict = verdict
        max_replans = limit(ctx, state, 'max_replans', 'runtime.max_replans', 1)
        if (verdict == Verdict.FAIL and step.attempts < step.max_attempts
                and state.replans < max_replans):
            notes.append(self.note(f'{step.id} retry via recovery (attempt {step.attempts}/'
                                   f'{step.max_attempts}, replans {state.replans}/{max_replans})'))
            return update(state, ctx, notes=notes, plan=plan, screen=after, next_agent='recovery')
        return self._done(state, ctx, plan, notes, screen=after)
