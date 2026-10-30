"""LangGraph supervisor: wires the agents into one state graph.

    preflight -> planner -> {navigator | typist | gameplay} -> verifier
                    ^                                           |
                    +---------------- recovery <----------------+
    any agent -> reporter -> END

Each node calls Agent.run(state, ctx) and returns a partial RunState update;
routing is the `next_agent` field the agent sets. The supervisor enforces the
global safety net: step cap, LLM budget and wall-clock timeout always end in
the reporter, never in a silent loop.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from ..agents.base import Ctx
from ..agents.gameplay import GameplayAgent
from ..agents.navigator import NavigatorAgent
from ..agents.planner import PlannerAgent
from ..agents.preflight import PreflightAgent
from ..agents.recovery import RecoveryAgent
from ..agents.reporter import ReporterAgent
from ..agents.typist import TypistAgent
from ..agents.verifier import VerifierAgent
from ..core import llm
from ..core.evidence import Evidence
from ..core.settings import Settings, get_settings
from ..core.state import RunState, Scenario, Verdict

NODES = ("preflight", "planner", "navigator", "typist", "gameplay",
         "verifier", "recovery", "reporter")


def _agents() -> dict[str, Any]:
    return {"preflight": PreflightAgent(), "planner": PlannerAgent(),
            "navigator": NavigatorAgent(), "typist": TypistAgent(),
            "gameplay": GameplayAgent(), "verifier": VerifierAgent(),
            "recovery": RecoveryAgent(), "reporter": ReporterAgent()}


def build_graph(ctx: Ctx, settings: Settings | None = None, checkpointer: Any = None):
    s = settings or get_settings()
    agents = _agents()
    timeout = float(s.get("runtime.run_timeout_seconds", 3600) or 3600)
    max_calls = int(s.get("llm.max_calls_per_run", 150) or 150)

    def node(name: str):
        agent = agents[name]

        def fn(state: RunState) -> dict[str, Any]:
            ctx.evidence.log("node", agent=name, cursor=state.cursor, steps=state.steps_taken)
            t0 = time.time()
            upd = agent.run(state, ctx)
            ctx.evidence.log("node_done", agent=name, next=upd.get("next_agent"),
                             seconds=round(time.time() - t0, 2))
            if name == "reporter":
                return upd
            # Global guards (supervisor-level, independent of agent logic).
            reason = ""
            if time.time() - state.started > timeout:
                reason = f"run timeout {timeout:.0f}s"
            elif llm.snapshot_metrics()["calls"] > max_calls:
                reason = f"LLM budget exceeded ({max_calls} calls)"
            if reason:
                upd["next_agent"] = "reporter"
                upd.setdefault("verdict", Verdict.BLOCKED)
                upd.setdefault("verdict_reason", reason)
            elif upd.get("next_agent") not in NODES:
                upd["next_agent"] = "reporter"
            return upd
        return fn

    g = StateGraph(RunState)
    for n in NODES:
        g.add_node(n, node(n))
    g.set_entry_point("preflight")

    def route(state: RunState) -> str:
        nxt = state.next_agent
        return END if nxt in ("end", None) else (nxt if nxt in NODES else "reporter")

    for n in NODES:
        if n == "reporter":
            g.add_edge("reporter", END)
        else:
            g.add_conditional_edges(n, route, {**{x: x for x in NODES}, END: END})
    return g.compile(checkpointer=checkpointer)


def new_run_dir(scenario: Scenario, settings: Settings | None = None) -> tuple[str, Path]:
    s = settings or get_settings()
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{scenario.id}-{uuid.uuid4().hex[:4]}"
    d = s.artifacts_dir / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return run_id, d


def run_scenario(scenario: Scenario, rig: Any, settings: Settings | None = None,
                 checkpoint: bool = True) -> RunState:
    """Run one scenario end-to-end through the graph. Returns the final RunState."""
    s = settings or get_settings()
    run_id, run_dir = new_run_dir(scenario, s)
    ev = Evidence(run_dir)
    ctx = Ctx.build(rig, ev, scenario, s)
    ev.log("run_start", run_id=run_id, scenario=scenario.id, type=scenario.type)
    _run_actions(ctx, scenario.setup, "setup")
    saver = None
    if checkpoint:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        saver = SqliteSaver(sqlite3.connect(str(run_dir / "checkpoints.sqlite"),
                                            check_same_thread=False))
    graph = build_graph(ctx, s, saver)
    init = RunState(run_id=run_id, scenario=scenario, run_dir=str(run_dir))
    cfg = {"configurable": {"thread_id": run_id},
           "recursion_limit": int(s.get("runtime.recursion_limit", 150) or 150)}
    try:
        out = graph.invoke(init, cfg)
        final = out if isinstance(out, RunState) else RunState.model_validate(out)
    except Exception as exc:  # noqa: BLE001 - any crash must still produce a report
        ev.log("run_crash", error=repr(exc))
        snap = graph.get_state(cfg).values if saver else {}
        final = RunState.model_validate(snap) if snap else init
        final = final.model_copy(update={"verdict": Verdict.BLOCKED,
                                         "verdict_reason": f"runner crashed: {exc!r}"})
        from ..reporting.report import write_report
        write_report(final, run_dir)
    _run_actions(ctx, scenario.teardown, "teardown")
    ev.log("run_end", verdict=final.verdict.value, reason=final.verdict_reason)
    return final


def _run_actions(ctx: Ctx, items: list[dict[str, Any]], tag: str) -> None:
    from ..agents.planner import parse_action
    from ..hw.adapters import perform
    for d in items or []:
        a = parse_action(d)
        ctx.evidence.log(tag, action=a.label())
        perform(ctx.rig, a)
        time.sleep(0.8)
