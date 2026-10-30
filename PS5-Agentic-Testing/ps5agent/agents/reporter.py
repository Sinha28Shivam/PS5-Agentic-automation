'''Reporter agent: finalises the verdict, snapshots LLM metrics and writes the run report.'''

from __future__ import annotations

import time
from typing import Any

from ps5agent.core import llm
from ps5agent.core.state import RunState, Step, Verdict
from ps5agent.reporting.report import write_report


def verdict_from_plan(plan: list[Step]) -> tuple[Verdict, str]:
    '''Any BLOCKED -> BLOCKED, any FAIL -> FAIL, all PASS -> PASS, otherwise BLOCKED (incomplete).'''
    if not plan:
        return Verdict.BLOCKED, 'incomplete: no plan'
    for v in (Verdict.BLOCKED, Verdict.FAIL):
        hit = [s for s in plan if s.verdict == v]
        if hit:
            s = hit[0]
            return v, f'step {s.id} {v.value}: {s.reason}'.rstrip(': ')
    if all(s.verdict == Verdict.PASS for s in plan):
        return Verdict.PASS, f'all {len(plan)} steps passed'
    pending = [s.id for s in plan if s.verdict != Verdict.PASS]
    return Verdict.BLOCKED, f"incomplete: steps not judged: {', '.join(pending)}"


class ReporterAgent:
    name = 'reporter'

    def run(self, state: RunState | dict[str, Any], ctx: Any) -> dict[str, Any]:
        st = state if isinstance(state, RunState) else RunState.model_validate(state)
        verdict, reason = st.verdict, st.verdict_reason
        if verdict == Verdict.PENDING:
            verdict, reason = verdict_from_plan(st.plan)
        metrics = {**st.metrics, 'llm': llm.snapshot_metrics()}
        finished = time.time()
        updates: dict[str, Any] = {'verdict': verdict, 'verdict_reason': reason,
                                   'finished': finished, 'metrics': metrics}
        final = st.model_copy(update=updates)
        paths = write_report(final, ctx.evidence.dir)
        log = getattr(ctx.evidence, 'log', None)
        if callable(log):
            log('report', verdict=verdict.value, reason=reason, **paths)
        return {**updates, 'next_agent': 'end'}
