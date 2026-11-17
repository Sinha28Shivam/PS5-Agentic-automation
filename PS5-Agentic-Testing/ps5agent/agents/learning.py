"""Conservative certification and lifecycle for persistent navigation strategies."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.navigation_memory import contract, known, meaningful, safe_actions
from ..core.state import NavigationAttempt, RunState, Verdict


def certified_plan(state: RunState) -> bool:
    return bool(state.plan) and len({s.id for s in state.plan}) == len(state.plan) and all(
        s.agent in ('navigator', 'verifier') and meaningful(s.expect) for s in state.plan)


def memory_call(ctx: Any, method: str, *args: Any) -> Any:
    memory = getattr(ctx, 'navigation_memory', None)
    if memory is None:
        return None
    try:
        return getattr(memory, method)(*args)
    except Exception as exc:
        ctx.navigation_memory = None
        ctx.learning_error = f'navigation memory disabled: {type(exc).__name__}'
        ctx.evidence.log('learning_disabled', reason=ctx.learning_error)
        return None


def provenance(state: RunState, attempt: NavigationAttempt) -> dict[str, Any]:
    return {'run_id': state.run_id, 'run_dir': state.run_dir, 'step_id': attempt.step_id,
            'contract': state.learning_contract, 'history_start': attempt.history_start,
            'history_end': attempt.history_end, 'verdict': attempt.verdict.value,
            'reason': attempt.reason, 'evidence': attempt.evidence}


def invalidate(state: RunState, ctx: Any, attempt: NavigationAttempt) -> None:
    if attempt.source != 'reused' or not attempt.key or attempt.invalidated_id:
        return
    result = memory_call(ctx, 'invalidate', attempt.key, attempt.generation,
                         provenance(state, attempt))
    attempt.invalidated_id = result
    attempt.memory_status = ('invalidated' if result else
                             getattr(ctx, 'learning_error', '') or 'invalidation CAS conflict or unavailable')


def pending(state: RunState) -> NavigationAttempt | None:
    step = state.current_step()
    if state.navigation_attempts and step:
        a = state.navigation_attempts[-1]
        if a.step_id == step.id and a.verdict == Verdict.PENDING:
            return a
    return None


def proof_error(state: RunState, attempt: NavigationAttempt | None) -> str:
    if contract(state) != state.learning_contract or not certified_plan(state):
        return 'learning contract changed or unsupported'
    if not known(state.screen):
        return 'learning verification needs a recognized, nonblank evidence frame'
    step = state.current_step()
    if step.agent == 'verifier':
        return 'standalone screen-change assertion has no attributable action' if step.expect.screen_changed is not None else ''
    if attempt is None or attempt.history_end != len(state.history):
        return 'missing or stale navigation attempt boundary'
    # Boundaries must address a real, forward slice of history. A negative or
    # inverted index would still slice "something" and fake an attributable window.
    if not 0 <= attempt.history_start <= attempt.history_end <= len(state.history):
        return 'missing or stale navigation attempt boundary'
    records = state.history[attempt.history_start:attempt.history_end]
    if not records or [r.action for r in records] != attempt.actions:
        return 'navigation strategy was not executed completely'
    if any(r.agent != 'navigator' or not r.allowed or not r.sent_ok or
           not r.before_frame or not Path(r.before_frame).is_file() or
           not r.after_frame or not Path(r.after_frame).is_file() for r in records):
        return 'navigation delivery or attributable before/after evidence missing'
    return ''


def finish_attempt(state: RunState, ctx: Any, verdict: Verdict, reason: str) -> RunState:
    st = state.model_copy(deep=True)
    a = pending(st)
    if a:
        a.verdict, a.reason = verdict, reason
        a.end = st.screen.model_copy(deep=True)
        a.evidence = [p for p in [a.start.frame_path, st.screen.frame_path] if p]
        for rec in st.history[a.history_start:a.history_end]:
            a.evidence.extend(p for p in (rec.before_frame, rec.after_frame) if p)
        a.evidence = list(dict.fromkeys(a.evidence))
        if verdict != Verdict.PASS:
            invalidate(st, ctx, a)
    step = st.current_step()
    if step and verdict == Verdict.PASS and step.id not in st.learning_verified:
        st.learning_verified.append(step.id)
    error = getattr(ctx, 'learning_error', '')
    if error and error not in st.notes:
        st.notes.append(error)
    return st


def finalize_learning(state: RunState, ctx: Any) -> RunState:
    st = state.model_copy(deep=True)
    for a in st.navigation_attempts:
        if a.verdict == Verdict.PENDING:
            a.verdict, a.reason = Verdict.BLOCKED, 'attempt ended without original-assertion verification'
            invalidate(st, ctx, a)
    complete = (st.learning_contract and contract(st) == st.learning_contract
                and certified_plan(st) and st.verdict == Verdict.PASS
                and all(s.verdict == Verdict.PASS for s in st.plan)
                and set(st.learning_verified) == {s.id for s in st.plan})
    if complete:
        latest = {a.step_id: a for a in st.navigation_attempts}
        for index, step in enumerate(st.plan):
            if not step.evidence or not Path(step.evidence[-1]).is_file():
                complete = False
                break
            if step.agent != 'navigator':
                continue
            a = latest.get(step.id)
            if not a or a.verdict != Verdict.PASS or a.end is None:
                complete = False
                break
            proof = st.model_copy(update={'cursor': index, 'screen': a.end,
                                          'history': st.history[:a.history_end]})
            if proof_error(proof, a):
                complete = False
                break
    if st.learning_contract and st.verdict == Verdict.PASS and not complete:
        st.verdict, st.verdict_reason = Verdict.BLOCKED, 'learning run lacks complete original-plan proof'
    if complete:
        for a in st.navigation_attempts:
            if a.source != 'correction' or a.verdict != Verdict.PASS or not a.key or a.promoted_id:
                continue
            try:
                actions = safe_actions([x.model_dump(mode='json') for x in a.actions])
            except (ValueError, TypeError):
                a.memory_status = 'not promoted: unsupported actions'
                continue
            result = memory_call(ctx, 'append', a.key, a.generation, actions, provenance(st, a))
            a.promoted_id = result
            a.memory_status = ('promoted' if result else
                               getattr(ctx, 'learning_error', '') or 'promotion CAS conflict or unavailable')
    error = getattr(ctx, 'learning_error', '')
    if error and error not in st.notes:
        st.notes.append(error)
    return st
