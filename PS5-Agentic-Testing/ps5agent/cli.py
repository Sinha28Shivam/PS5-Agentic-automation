"""ps5agent CLI.

    python -m ps5agent run scenarios/system_ui/search_game.yaml
    python -m ps5agent run --goal "Open Settings and go to System" --type system_ui
    python -m ps5agent suite suites/smoke.yaml
    python -m ps5agent soak scenarios/soak/home_soak.yaml --minutes 5
    python -m ps5agent explore --game mk11 --seconds 60
    python -m ps5agent screens            # classify the current screen (no input)
    python -m ps5agent graph              # print the agent graph (mermaid)
    --dry-run replays tests/fixtures/frames through FakeRig (no hardware)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from .core.settings import PKG_ROOT, get_settings
from .core.state import RunState, Scenario, Verdict


def load_scenario(path: str | Path) -> Scenario:
    p = Path(path)
    if not p.is_absolute():
        p = (PKG_ROOT / p) if (PKG_ROOT / p).exists() else p
    return Scenario.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))


def make_rig(dry: bool, frames: str | None = None) -> Any:
    from .hw.adapters import FakeRig, Rig
    if dry:
        return FakeRig(frames or (PKG_ROOT / "tests" / "fixtures" / "frames"))
    return Rig()


def _print_result(st: RunState) -> None:
    colour = {"PASS": "\033[92m", "FAIL": "\033[91m"}.get(st.verdict.value, "\033[93m")
    print(f"\n{colour}{st.verdict.value}\033[0m  {st.scenario.id}: {st.verdict_reason}")
    for s in st.plan:
        print(f"   [{s.verdict.value:7}] {s.id}: {s.reason[:110]}")
    print(f"   report: {Path(st.run_dir) / 'report.html'}")


def cmd_run(a: argparse.Namespace) -> int:
    from .graph.build import run_scenario
    if a.goal:
        sc = Scenario(id=a.id or "adhoc", goal=a.goal, type=a.type, game=a.game,
                      setup=[{"macro": "open_home"}] if a.type == "system_ui" else [])
    else:
        sc = load_scenario(a.scenario)
    rig = make_rig(a.dry_run)
    try:
        st = run_scenario(sc, rig)
    finally:
        rig.close()
    _print_result(st)
    return 0 if st.verdict == Verdict.PASS else 1


def cmd_suite(a: argparse.Namespace) -> int:
    from .graph.build import run_scenario
    from .reporting.suite_report import write_suite_report
    suite = yaml.safe_load((PKG_ROOT / a.suite if not Path(a.suite).is_absolute()
                            else Path(a.suite)).read_text(encoding="utf-8"))
    rig = make_rig(a.dry_run)
    results = []
    try:
        for path in suite["scenarios"]:
            sc = load_scenario(path)
            if a.tag and a.tag not in sc.tags:
                continue
            t0 = time.time()
            st = run_scenario(sc, rig)
            _print_result(st)
            results.append({"scenario_id": sc.id, "verdict": st.verdict.value,
                            "reason": st.verdict_reason, "run_dir": st.run_dir,
                            "duration": round(time.time() - t0, 1)})
    finally:
        rig.close()
    out = get_settings().reports_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{suite['name']}"
    paths = write_suite_report(suite["name"], results, out)
    n_pass = sum(r["verdict"] == "PASS" for r in results)
    print(f"\nSUITE {suite['name']}: {n_pass}/{len(results)} PASS -> {paths.get('suite_html')}")
    return 0 if n_pass == len(results) else 1


def cmd_soak(a: argparse.Namespace) -> int:
    """Repeat a scenario for N minutes with the Monitor watching in parallel."""
    from .agents.monitor import Monitor
    from .graph.build import run_scenario
    from .hw.adapters import ds4_present
    from .reporting.suite_report import write_suite_report
    sc = load_scenario(a.scenario)
    minutes = a.minutes or float(sc.limits.get("soak_minutes", 5))
    rig = make_rig(a.dry_run)
    lock = threading.Lock()
    events: list[dict[str, Any]] = []
    orig_grab = rig.grab

    def locked_grab():
        with lock:
            return orig_grab()
    rig.grab = locked_grab
    mon = Monitor(grab_fn=orig_grab, lock=lock, interval=3.0,
                  freeze_seconds=float(sc.limits.get("freeze_seconds", 60)),
                  on_event=lambda e, d: (events.append({"event": e, **d}),
                                         print(f"  [monitor] {e} {d}")),
                  ds4_fn=None if a.dry_run else ds4_present)
    mon.start()
    results = []
    deadline = time.time() + minutes * 60
    i = 0
    try:
        while time.time() < deadline:
            i += 1
            t0 = time.time()
            st = run_scenario(sc.model_copy(update={"id": f"{sc.id}-{i:03d}"}), rig,
                              checkpoint=False)
            print(f"  iteration {i}: {st.verdict.value} {st.verdict_reason[:80]}")
            results.append({"scenario_id": f"{sc.id}-{i:03d}", "verdict": st.verdict.value,
                            "reason": st.verdict_reason, "run_dir": st.run_dir,
                            "duration": round(time.time() - t0, 1)})
            if st.verdict == Verdict.BLOCKED and "dead" in st.verdict_reason:
                break
    finally:
        mon.stop()
        rig.close()
    out = get_settings().reports_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-soak-{sc.id}"
    paths = write_suite_report(f"soak-{sc.id}", results, out)
    (Path(out) / "monitor.json").write_text(json.dumps(
        {"summary": mon.summary(), "events": events}, indent=2, default=str), encoding="utf-8")
    n_pass = sum(r["verdict"] == "PASS" for r in results)
    print(f"\nSOAK {sc.id}: {i} iterations, {n_pass} PASS, monitor={mon.summary()} -> "
          f"{paths.get('suite_html')}")
    return 0 if n_pass == len(results) and mon.healthy else 1


def cmd_explore(a: argparse.Namespace) -> int:
    from .graph.build import run_scenario
    sc = Scenario(id=f"{a.game}_explore", type="gameplay_explore", game=a.game,
                  goal=f"Fight autonomously in {a.game} for {a.seconds}s",
                  steps=[{"id": "explore", "goal": "explore: play the fight", "agent": "gameplay",
                          "expect": {"hud": {"in_fight": True}}}],
                  limits={"explore_seconds": a.seconds, "max_steps": 400,
                          "skip_input_probe": True})
    rig = make_rig(a.dry_run)
    try:
        st = run_scenario(sc, rig)
    finally:
        rig.close()
    _print_result(st)
    print("   gameplay:", json.dumps(st.metrics.get("gameplay", {}), default=str)[:400])
    return 0 if st.verdict == Verdict.PASS else 1


def cmd_screens(a: argparse.Namespace) -> int:
    from .perception.perceive import Perception
    rig = make_rig(a.dry_run)
    try:
        f = rig.grab()
        st = Perception().observe(f, use_vision="always" if a.vision else "never")
    finally:
        rig.close()
    print(json.dumps({"screen": st.screen_id, "confidence": st.confidence, "source": st.source,
                      "candidates": st.extras.get("candidates"), "danger": st.extras.get("danger"),
                      "text": st.text[:300]}, indent=2, default=str))
    return 0


def cmd_graph(a: argparse.Namespace) -> int:
    from .agents.base import Ctx
    from .core.evidence import Evidence
    from .graph.build import build_graph
    import tempfile
    sc = Scenario(id="graph", goal="graph")
    rig = make_rig(True)
    ctx = Ctx.build(rig, Evidence(tempfile.mkdtemp()), sc)
    print(build_graph(ctx).get_graph().draw_mermaid())
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ps5agent", description="Multi-agent PS5 test runner")
    ap.add_argument("--dry-run", action="store_true", help="replay fixture frames, no hardware")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("scenario", nargs="?")
    r.add_argument("--goal"); r.add_argument("--id"); r.add_argument("--game")
    r.add_argument("--type", default="system_ui")
    s = sub.add_parser("suite"); s.add_argument("suite"); s.add_argument("--tag")
    k = sub.add_parser("soak"); k.add_argument("scenario"); k.add_argument("--minutes", type=float)
    e = sub.add_parser("explore"); e.add_argument("--game", default="mk11")
    e.add_argument("--seconds", type=float, default=60)
    c = sub.add_parser("screens"); c.add_argument("--vision", action="store_true")
    sub.add_parser("graph")
    a = ap.parse_args(argv)
    if a.cmd == "run" and not (a.scenario or a.goal):
        ap.error("run needs a scenario file or --goal")
    return {"run": cmd_run, "suite": cmd_suite, "soak": cmd_soak, "explore": cmd_explore,
            "screens": cmd_screens, "graph": cmd_graph}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
