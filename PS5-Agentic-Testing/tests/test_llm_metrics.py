'''LLM token/call metrics are per-run (not cumulative across a suite) and reach every report.'''

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ps5agent.core import llm
from ps5agent.core.state import RunState, Scenario, Verdict
from ps5agent.graph import build as build_mod
from ps5agent.reporting.suite_report import write_suite_report


def _spend(calls: int, tin: int, tout: int) -> None:
    with llm._lock:
        llm.METRICS['calls'] += calls
        llm.METRICS['input_tokens'] += tin
        llm.METRICS['output_tokens'] += tout


class FakeGraph:
    def __init__(self, spend: tuple[int, int, int], crash: bool = False):
        self.spend, self.crash = spend, crash

    def invoke(self, init: RunState, cfg: dict[str, Any]) -> RunState:
        _spend(*self.spend)
        if self.crash:
            raise RuntimeError('boom')
        return init.model_copy(update={'verdict': Verdict.PASS,
                                       'metrics': {'llm': llm.snapshot_metrics()}})

    def get_state(self, cfg: dict[str, Any]) -> Any:
        return SimpleNamespace(values={})


@pytest.fixture
def patched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[FakeGraph]:
    graphs: list[FakeGraph] = []
    counter = iter(range(100))

    def new_run_dir(scenario: Scenario, settings: Any = None) -> tuple[str, Path]:
        d = tmp_path / f'run{next(counter)}'
        d.mkdir()
        return d.name, d

    monkeypatch.setattr(build_mod, 'new_run_dir', new_run_dir)
    monkeypatch.setattr(build_mod.Ctx, 'build', classmethod(lambda cls, *a, **k: SimpleNamespace()))
    monkeypatch.setattr(build_mod, 'build_graph', lambda ctx, s, saver: graphs.pop(0))
    llm.reset_metrics()
    return graphs


def test_reset_metrics_zeroes_counters() -> None:
    _spend(4, 1000, 200)
    llm.reset_metrics()
    m = llm.snapshot_metrics()
    assert (m['calls'], m['input_tokens'], m['output_tokens'], m['errors']) == (0, 0, 0, 0)


def test_tokens_are_per_run_not_cumulative(patched: list[FakeGraph]) -> None:
    patched += [FakeGraph((3, 500, 50)), FakeGraph((2, 300, 30))]
    sc = Scenario(id='s', goal='g')
    a = build_mod.run_scenario(sc, rig=None, settings=SimpleNamespace(get=lambda k, d=None: d),
                               checkpoint=False)
    b = build_mod.run_scenario(sc, rig=None, settings=SimpleNamespace(get=lambda k, d=None: d),
                               checkpoint=False)
    assert a.metrics['llm']['calls'] == 3 and a.metrics['llm']['input_tokens'] == 500
    assert b.metrics['llm']['calls'] == 2 and b.metrics['llm']['input_tokens'] == 300


def test_crash_report_includes_tokens(patched: list[FakeGraph]) -> None:
    patched.append(FakeGraph((1, 120, 12), crash=True))
    st = build_mod.run_scenario(Scenario(id='s', goal='g'), rig=None,
                                settings=SimpleNamespace(get=lambda k, d=None: d), checkpoint=False)
    assert st.verdict == Verdict.BLOCKED and 'crashed' in st.verdict_reason
    assert st.metrics['llm']['input_tokens'] == 120
    data = json.loads((Path(st.run_dir) / 'result.json').read_text(encoding='utf-8'))
    assert data['summary']['llm']['input_tokens'] == 120


def test_suite_report_totals_tokens(tmp_path: Path) -> None:
    results: list[dict[str, Any]] = [
        {'scenario_id': 'a', 'verdict': 'PASS', 'duration': 1,
         'llm': {'calls': 3, 'input_tokens': 500, 'output_tokens': 50, 'seconds': 1.2}},
        {'scenario_id': 'b', 'verdict': 'FAIL', 'duration': 1,
         'llm': {'calls': 2, 'input_tokens': 300, 'output_tokens': 30}},
        {'scenario_id': 'c', 'verdict': 'BLOCKED', 'duration': 0},
    ]
    paths = write_suite_report('smoke', results, tmp_path / 'suite')
    js = json.loads(Path(paths['suite_json']).read_text(encoding='utf-8'))
    assert js['llm'] == {'calls': 5, 'input_tokens': 800, 'output_tokens': 80, 'errors': 0}
    assert js['results'][2]['llm']['calls'] == 0
    html = Path(paths['suite_html']).read_text(encoding='utf-8')
    assert 'tokens in/out 800 / 80' in html and '500 / 50' in html
