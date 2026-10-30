'''Offline tests for reporting, ReporterAgent and Monitor (synthetic frames, no hardware).'''

from __future__ import annotations

import json
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from ps5agent.agents import reporter as reporter_mod
from ps5agent.agents.monitor import Monitor
from ps5agent.agents.reporter import ReporterAgent, verdict_from_plan
from ps5agent.core.evidence import Evidence
from ps5agent.core.state import Action, ActionRecord, RunState, Scenario, Step, Verdict
from ps5agent.reporting.report import write_report
from ps5agent.reporting.suite_report import write_suite_report


def noise(seed: int, shape: tuple[int, int, int] = (36, 64, 3)) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 255, shape, dtype=np.uint8)


def make_state(tmp_path: Path) -> tuple[RunState, Evidence]:
    ev = Evidence(tmp_path / 'run1')
    f = [ev.save_frame(noise(i), f'f{i}') for i in range(4)]
    t0 = time.time() - 10
    hist = [
        ActionRecord(action=Action(kind='press', name='cross', reason='open'), agent='navigator',
                     sent_ok=True, before_frame=f[0], after_frame=f[1], delta=12.5, changed=True, ts=t0 + 1),
        ActionRecord(action=Action(kind='press', name='ps', times=2), agent='navigator', allowed=False,
                     blocked_reason='ps button not allowed <here>', ts=t0 + 2),
        ActionRecord(action=Action(kind='type', text='mk11'), agent='typist', sent_ok=True,
                     before_frame=f[1], after_frame=f[2], delta=0.1, changed=False, ts=t0 + 3),
    ]
    plan = [Step(id='s1', goal='open search', verdict=Verdict.PASS, reason='search shown', attempts=1,
                 evidence=[f[1]]),
            Step(id='s2', goal='type query', agent='typist', verdict=Verdict.FAIL, reason='no results',
                 attempts=3, evidence=[f[2], f[3]])]
    state = RunState(run_id='r1', scenario=Scenario(id='search_mk11', goal='Search for MK11', tags=['smoke']),
                     run_dir=str(ev.dir), plan=plan, history=hist, notes=['planner: 2 steps', 'verifier: s2 failed'],
                     health={'capture': 'ok', 'ds4': True}, metrics={'gameplay': {'moves': 4, 'specials': 1}},
                     started=t0, verdict=Verdict.FAIL, verdict_reason='s2 failed', finished=t0 + 9)
    return state, ev


def test_write_report(tmp_path: Path) -> None:
    state, ev = make_state(tmp_path)
    paths = write_report(state, ev.dir)
    res, html = Path(paths['result_json']), Path(paths['report_html'])
    assert res.is_file() and html.is_file()
    data = json.loads(res.read_text(encoding='utf-8'))
    s = data['summary']
    assert s['verdict'] == 'FAIL' and s['reason'] == 's2 failed' and s['duration'] == pytest.approx(9, abs=0.01)
    assert s['steps']['pass'] == 1 and s['steps']['fail'] == 1 and s['steps']['blocked'] == 0
    assert s['actions']['sent'] == 2 and s['actions']['blocked'] == 1
    rec = data['history'][0]
    assert rec['before_frame'].startswith('frames/') and (ev.dir / rec['after_frame']).is_file()
    assert all(e.startswith('frames/') for e in data['plan'][1]['evidence'])
    text = html.read_text(encoding='utf-8')
    assert 'id="verdict">FAIL<' in text and 'search_mk11' in text and 'Search for MK11' in text
    assert text.count('<img') == 7  # 2+2 action thumbs, 3 step evidence
    assert 'src="frames/' in text and str(tmp_path) not in text
    assert '&lt;here&gt;' in text and 'press:psx2' in text and "type(&#39;mk11&#39;)" in text
    assert 'specials' in text and 'verifier: s2 failed' in text


def test_reporter_agent_computes_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, ev = make_state(tmp_path)
    state = state.model_copy(update={'verdict': Verdict.PENDING, 'verdict_reason': '', 'finished': None})
    monkeypatch.setattr(reporter_mod.llm, 'snapshot_metrics',
                        lambda: {'calls': 3, 'input_tokens': 100, 'output_tokens': 20, 'seconds': 1.5, 'errors': 0})
    out = ReporterAgent().run(state, SimpleNamespace(evidence=ev))
    assert ReporterAgent.name == 'reporter' and out['next_agent'] == 'end'
    assert out['verdict'] == Verdict.FAIL and 's2' in out['verdict_reason'] and out['finished']
    assert out['metrics']['llm']['calls'] == 3 and out['metrics']['gameplay']['moves'] == 4
    data = json.loads((ev.dir / 'result.json').read_text(encoding='utf-8'))
    assert data['summary']['verdict'] == 'FAIL' and data['summary']['llm']['input_tokens'] == 100
    assert 'id="verdict">FAIL<' in (ev.dir / 'report.html').read_text(encoding='utf-8')
    assert state.verdict == Verdict.PENDING  # input not mutated


def test_verdict_from_plan() -> None:
    def plan(*vs: Verdict) -> list[Step]:
        return [Step(id=f's{i}', goal='g', verdict=v) for i, v in enumerate(vs)]
    assert verdict_from_plan(plan(Verdict.PASS, Verdict.PASS))[0] == Verdict.PASS
    assert verdict_from_plan(plan(Verdict.PASS, Verdict.FAIL))[0] == Verdict.FAIL
    assert verdict_from_plan(plan(Verdict.FAIL, Verdict.BLOCKED))[0] == Verdict.BLOCKED
    v, why = verdict_from_plan(plan(Verdict.PASS, Verdict.PENDING))
    assert v == Verdict.BLOCKED and 'incomplete' in why
    assert verdict_from_plan([])[0] == Verdict.BLOCKED


def test_suite_report(tmp_path: Path) -> None:
    state, ev = make_state(tmp_path)
    write_report(state, ev.dir)
    results: list[dict[str, Any]] = [
        {'scenario_id': 'search_mk11', 'verdict': 'FAIL', 'reason': 's2 failed', 'run_dir': str(ev.dir), 'duration': 9.0},
        {'scenario_id': 'open_settings', 'verdict': Verdict.PASS, 'reason': 'ok', 'run_dir': None, 'duration': 4.0},
        {'scenario_id': 'soak', 'verdict': 'BLOCKED', 'reason': 'no capture', 'run_dir': None, 'duration': 0.5},
        {'scenario_id': 'mk11_fight', 'verdict': 'SKIPPED', 'reason': 'game missing', 'duration': 0},
    ]
    paths = write_suite_report('smoke', results, tmp_path / 'suite')
    assert all(Path(p).is_file() for p in paths.values())
    js = json.loads(Path(paths['suite_json']).read_text(encoding='utf-8'))
    assert js['total'] == 4 and js['counts']['PASS'] == 1 and js['counts']['FAIL'] == 1
    html = Path(paths['suite_html']).read_text(encoding='utf-8')
    assert 'href="../run1/report.html"' in html and 'open_settings' in html
    suite = ET.parse(paths['junit_xml']).getroot().find('testsuite')
    assert suite is not None
    assert (suite.get('tests'), suite.get('failures'), suite.get('errors'), suite.get('skipped')) == ('4', '1', '1', '1')
    cases = {c.get('name'): c for c in suite.findall('testcase')}
    assert cases['search_mk11'].find('failure') is not None
    assert cases['soak'].find('error') is not None
    assert cases['mk11_fight'].find('skipped') is not None
    assert len(list(cases['open_settings'])) == 0


class Seq:
    '''Fake grab_fn: plays a list of frames then repeats the last one.'''

    def __init__(self, frames: list[np.ndarray | None]):
        self.frames, self.i, self.calls = frames, 0, 0

    def __call__(self) -> np.ndarray | None:
        self.calls += 1
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f


def names(m: Monitor) -> list[str]:
    return [e['event'] for e in m.events]


def test_monitor_freeze_once_and_clears() -> None:
    still = noise(1)
    m = Monitor(Seq([noise(0)] + [still] * 6 + [noise(2), noise(3)]), interval=0.01, freeze_seconds=0.025)
    t = 100.0
    for _ in range(9):
        m.tick(now=t)
        t += 0.01
    assert names(m) == ['freeze', 'freeze_cleared']
    assert m.counts['freeze'] == 1 and m.healthy


def test_monitor_no_freeze_when_motion_not_expected() -> None:
    m = Monitor(Seq([noise(1)]), interval=0.01, freeze_seconds=0.01, expect_motion_fn=lambda: False)
    for i in range(5):
        m.tick(now=float(i))
    assert names(m) == []


def test_monitor_thread_blank_ds4_home() -> None:
    frames: list[np.ndarray | None] = [noise(i) for i in range(3)] + [None, np.zeros((36, 64, 3), np.uint8)]
    frames += [noise(i) for i in range(10, 400)]
    grab = Seq(frames)
    ds4 = iter([True, True, False, False, False] + [True] * 1000)
    got: list[tuple[str, dict[str, Any]]] = []
    lock = threading.Lock()
    home = np.full((36, 64, 3), 7, np.uint8)
    home[:, :32] = 200
    home_after = {'n': 0}

    def home_fn(frame: np.ndarray) -> bool:
        home_after['n'] += 1
        return 12 <= home_after['n'] <= 14

    m = Monitor(grab, interval=0.005, freeze_seconds=10, on_event=lambda e, d: got.append((e, d)),
                ds4_fn=lambda: next(ds4), session_fn=lambda: True, home_detect_fn=home_fn, lock=lock)
    m.start()
    deadline = time.time() + 3
    while grab.calls < 30 and time.time() < deadline:
        time.sleep(0.01)
    with lock:  # caller-held lock blocks the monitor's grab
        before = grab.calls
        time.sleep(0.05)
        assert grab.calls == before
    m.stop()
    assert not m.is_alive()
    ev = names(m)
    for e in ('blank', 'blank_cleared', 'ds4_lost', 'ds4_lost_cleared', 'crash_to_home', 'crash_to_home_cleared'):
        assert ev.count(e) == 1, (e, ev)
    assert 'freeze' not in ev and 'session_lost' not in ev
    assert [e for e, _ in got] == ev and all('ts' in e for e in m.events)
    s = m.summary()
    assert s['counts']['blank'] == 1 and s['counts']['ds4_lost'] == 1 and s['healthy'] and s['ticks'] >= 30


def test_monitor_grab_errors_and_session_lost() -> None:
    def boom() -> np.ndarray:
        raise RuntimeError('capture gone')
    m = Monitor(boom, session_fn=lambda: False)
    m.tick(now=1.0)
    m.tick(now=2.0)
    assert names(m) == ['blank', 'session_lost'] and m.errors == 2
    assert m.summary()['active'] == ['blank', 'session_lost']
