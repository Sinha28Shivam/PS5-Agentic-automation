"""Offline agent tests: FakeRig + synthetic frames + scripted Perception. No hardware, no network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ps5agent.agents import base, gameplay, typist
from ps5agent.agents.base import Ctx, load_prompt
from ps5agent.agents.gameplay import GameplayAgent, hud_diff
from ps5agent.agents.navigator import NavigatorAgent
from ps5agent.agents.planner import PlannerAgent, parse_action, parse_step
from ps5agent.agents.preflight import PreflightAgent
from ps5agent.agents.recovery import RecoveryAgent
from ps5agent.agents.typist import TypistAgent
from ps5agent.agents.verifier import VerifierAgent, check_expectation
from ps5agent.core import llm
from ps5agent.core.evidence import Evidence
from ps5agent.core.settings import get_settings
from ps5agent.core.state import (Action, Expectation, RunState, Scenario, ScreenState, Step,
                                 Verdict)
from ps5agent.hw.adapters import FakeRig
from ps5agent.perception.perceive import Perception
from ps5agent.safety import action_gate as ag
from ps5agent.safety.action_gate import ActionGate


class FakeSettings:
    def __init__(self, tmp: Path, **over: Any):
        real = get_settings()
        self.prompts_dir = real.prompts_dir
        self.controls_config = real.controls_config
        self.config_dir = tmp
        self.data = {'runtime.max_steps': 40, 'runtime.dead_input_streak': 3,
                     'verification.screen_change_threshold': 0.5, 'runtime.max_replans': 1,
                     'runtime.max_recoveries': 3, 'llm.max_calls_per_run': 150,
                     'gameplay.tick_seconds': 1.5, **over}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def frame(v: int) -> np.ndarray:
    f = np.full((270, 480, 3), v, np.uint8)
    f[10:20, 10:20] = 255 - v                      # not blank (std > 1)
    return f


def frames(n: int, start: int = 20, step: int = 15) -> list[np.ndarray]:
    return [frame((start + i * step) % 230) for i in range(n)]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, 'available', lambda: False)
    monkeypatch.setattr(base, 'SETTLE_OVERRIDE', 0.0)
    monkeypatch.setattr(ag, 'MIN_INTERVAL', 0.0)
    monkeypatch.setattr(gameplay, 'SLEEP', lambda s: None)


def script(monkeypatch: pytest.MonkeyPatch, *screens: ScreenState) -> list[ScreenState]:
    '''Perception.observe returns these in order (last one repeats).'''
    queue = [s.model_copy(deep=True) for s in screens]

    def fake(self: Perception, frm: np.ndarray, evidence: Evidence | None = None,
             use_vision: str = 'auto', tag: str = '') -> ScreenState:
        s = (queue.pop(0) if len(queue) > 1 else queue[0]).model_copy(deep=True)
        if evidence is not None and frm is not None:
            s.frame_path = evidence.save_frame(frm, tag or s.screen_id)
        return s

    monkeypatch.setattr(Perception, 'observe', fake)
    return queue


def scr(sid: str = 'home', text: str = '', **kw: Any) -> ScreenState:
    return ScreenState(screen_id=sid, text=text, confidence=0.9, source='signature', **kw)


def make(tmp_path: Path, scenario: Scenario | None = None, fr: list[np.ndarray] | None = None,
         profile: dict[str, Any] | None = None, rig: Any = None, **over: Any
         ) -> tuple[RunState, Ctx, Any]:
    sc = scenario or Scenario(id='t', goal='g')
    rig = rig or FakeRig(frames=fr or frames(12))
    ev = Evidence(tmp_path / 'run')
    fs = FakeSettings(tmp_path, **over)
    ctx = Ctx(rig=rig, gate=ActionGate(rig, ev, sc, fs), perception=Perception(), evidence=ev,
              settings=fs, game_profile=profile)
    return RunState(run_id='r1', scenario=sc, run_dir=str(tmp_path / 'run')), ctx, rig


def merged(state: RunState, upd: dict[str, Any]) -> RunState:
    return state.model_copy(update=upd)


# ---------------------------------------------------------------- planner / parsing

def test_parse_action_shorthands() -> None:
    assert parse_action({'macro': 'open_home'}) == Action(kind='macro', name='open_home')
    a = parse_action({'press': 'Cross', 'times': 3, 'interval': 0.4})
    assert (a.kind, a.name, a.times, a.interval) == ('press', 'cross', 3, 0.4)
    assert parse_action({'button': 'down'}).kind == 'press'
    t = parse_action({'type': 'astro bot'})
    assert (t.kind, t.text) == ('type', 'astro bot')
    h = parse_action({'hold': 'r2', 'duration': 1.5})
    assert (h.kind, h.name, h.duration) == ('hold', 'r2', 1.5)
    assert parse_action({'hold': 'l1'}).duration == 1.0
    assert parse_action({'wait': 2}) == Action(kind='wait', duration=2.0)
    s = parse_action({'stick': 'left_stick', 'direction': 'right', 'duration': 0.3})
    assert (s.kind, s.name, s.direction, s.duration) == ('stick', 'left_stick', 'right', 0.3)
    assert parse_action({'trigger': 'r2', 'value': 255}).value == 255
    assert parse_action({'combo': 'uppercut'}).name == 'combo:uppercut'
    assert parse_action({'kind': 'press', 'name': 'circle', 'times': 2}).times == 2
    assert parse_action('macro:open_search') == Action(kind='macro', name='open_search')
    assert parse_action('triangle') == Action(kind='press', name='triangle')
    with pytest.raises(ValueError):
        parse_action({'jump': 'x'})


def test_parse_step_variants() -> None:
    s = parse_step({'goal': 'go home', 'actions': [{'macro': 'open_home'}],
                    'expect': {'screen': 'home', 'text_contains': 'games'}}, 0)
    assert (s.id, s.agent, s.expect.screen, s.expect.text_contains) == ('s1', 'navigator', 'home', ['games'])
    assert parse_step({'type': 'astro'}, 1).agent == 'typist'
    assert parse_step({'combo': 'uppercut'}, 2).agent == 'gameplay'
    assert parse_step({'id': 'v', 'agent': 'verifier', 'expect': {'screen': 'home'}}, 3).actions == []
    with pytest.raises(ValueError):
        parse_step({'agent': 'pilot'}, 0)


def test_planner_from_hints_adds_verify_step(tmp_path: Path) -> None:
    sc = Scenario(id='search', goal='search astro bot',
                  hints=[{'macro': 'open_home'}, {'macro': 'open_search'}, {'type': 'astro bot'},
                         {'macro': 'submit_search'}],
                  expect=[{'text_contains': ['astro bot']}, {'vision': 'results shown'}])
    state, ctx, _ = make(tmp_path, sc)
    up = PlannerAgent().run(state, ctx)
    plan = up['plan']
    assert [s.agent for s in plan] == ['navigator', 'navigator', 'typist', 'navigator', 'verifier']
    assert plan[-1].expect.text_contains == ['astro bot'] and plan[-1].expect.vision == 'results shown'
    assert up['next_agent'] == 'navigator' and up['cursor'] == 0


def test_planner_from_explicit_steps(tmp_path: Path) -> None:
    sc = Scenario(id='s', goal='g', hints=[{'macro': 'x'}],
                  steps=[{'id': 'a', 'goal': 'type', 'agent': 'typist', 'actions': [{'type': 'hi'}]},
                         {'id': 'b', 'goal': 'check', 'agent': 'verifier', 'expect': {'screen': 'home'}}])
    state, ctx, _ = make(tmp_path, sc)
    up = PlannerAgent().run(state, ctx)
    assert [s.id for s in up['plan']] == ['a', 'b'] and up['next_agent'] == 'typist'


def test_planner_without_hints_or_llm_is_blocked(tmp_path: Path) -> None:
    state, ctx, _ = make(tmp_path, Scenario(id='s', goal='open settings'))
    up = PlannerAgent().run(state, ctx)
    assert up['verdict'] == Verdict.BLOCKED and up['next_agent'] == 'reporter'


def test_prompts_exist() -> None:
    for name in ('planner', 'navigator', 'verifier', 'recovery', 'gameplay'):
        assert 'JSON' in load_prompt(name)


# ---------------------------------------------------------------- preflight

def test_preflight_ds4_missing_is_warning_input_probe_decides(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    # Unchanged frames -> probe sees no change -> BLOCKED, and the reason names the DS4.
    script(monkeypatch, scr())
    state, ctx, rig = make(tmp_path, fr=[np.random.default_rng(0).integers(0, 255, (270, 480, 3), dtype=np.uint8)])
    monkeypatch.setattr(rig, 'ds4_present', lambda: False)
    up = PreflightAgent().run(state, ctx)
    assert up['health']['ds4'] == 'not_enumerated'
    assert up['verdict'] == Verdict.BLOCKED and up['next_agent'] == 'reporter'
    assert up['health']['input'] == 'unproven' and 'probe' in up['verdict_reason']


def test_preflight_blocked_on_blank_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, ScreenState(blank=True))
    state, ctx, _ = make(tmp_path, fr=[np.zeros((270, 480, 3), np.uint8)])
    up = PreflightAgent().run(state, ctx)
    assert up['health']['capture'] == 'blank' and up['verdict'] == Verdict.BLOCKED


def test_preflight_probe_proves_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    state, ctx, rig = make(tmp_path)
    up = PreflightAgent().run(state, ctx)
    assert up['next_agent'] == 'planner' and up['health']['input'] == 'ok'
    assert rig.actions == ['macro:open_home', 'press:triangle', 'press:down']
    assert len(up['history']) == 3


def test_preflight_probe_no_change_is_unproven(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    state, ctx, _ = make(tmp_path, fr=[frame(60)])
    up = PreflightAgent().run(state, ctx)
    assert up['health']['input'] == 'unproven' and up['verdict'] == Verdict.BLOCKED
    assert up['next_agent'] == 'reporter'


def test_preflight_skip_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    state, ctx, rig = make(tmp_path, Scenario(id='s', goal='g', limits={'skip_input_probe': True}))
    up = PreflightAgent().run(state, ctx)
    assert up['next_agent'] == 'planner' and up['health']['input'] == 'skipped' and not rig.actions


# ---------------------------------------------------------------- navigator

def _with_plan(state: RunState, *steps: Step, **kw: Any) -> RunState:
    return state.model_copy(update={'plan': list(steps), 'cursor': 0, **kw})


def test_navigator_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    state, ctx, rig = make(tmp_path)
    step = parse_step({'actions': [{'macro': 'open_home'}, {'press': 'right', 'times': 2}],
                       'expect': {'screen': 'home'}}, 0)
    state = _with_plan(state, step, notes=['old'])
    up = NavigatorAgent().run(state, ctx)
    assert rig.actions == ['macro:open_home', 'press:right', 'press:right']
    assert up['next_agent'] == 'verifier' and len(up['history']) == 2
    assert up['notes'][0] == 'old' and up['plan'][0].attempts == 1
    assert state.plan[0].attempts == 0 and state.history == []      # input state untouched
    assert up['steps_taken'] == 2 and up['screen'].frame_path


def test_navigator_dead_input_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    state, ctx, rig = make(tmp_path, fr=[frame(80)])
    state = _with_plan(state, parse_step({'actions': [{'press': 'right'}] * 5}, 0))
    up = NavigatorAgent().run(state, ctx)
    assert up['verdict'] == Verdict.BLOCKED and up['next_agent'] == 'reporter'
    assert 'dead_input' in up['verdict_reason'] and len(rig.actions) == 3


def test_navigator_danger_denial_goes_to_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('store'))
    state, ctx, rig = make(tmp_path)
    danger = scr('store', 'playstation store add to cart', frame_path='x.jpg', extras={'danger': 'store'})
    state = _with_plan(state, parse_step({'actions': [{'press': 'cross'}]}, 0), screen=danger)
    up = NavigatorAgent().run(state, ctx)
    assert up['next_agent'] == 'recovery' and rig.actions == []


def test_navigator_goal_only_without_llm_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    state, ctx, _ = make(tmp_path)
    state = _with_plan(state, Step(id='s1', goal='open settings'))
    up = NavigatorAgent().run(state, ctx)
    assert up['verdict'] == Verdict.BLOCKED and up['plan'][0].verdict == Verdict.BLOCKED


def test_navigator_llm_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr())
    monkeypatch.setattr(llm, 'available', lambda: True)
    replies = [{'done': False, 'actions': [{'press': 'right'}, {'kind': 'press', 'name': 'down'}],
                'reason': 'move'}, {'done': True, 'reason': 'there'}]
    monkeypatch.setattr(llm, 'ask', lambda *a, **k: replies.pop(0))
    state, ctx, rig = make(tmp_path)
    state = _with_plan(state, Step(id='s1', goal='focus settings'))
    up = NavigatorAgent().run(state, ctx)
    assert rig.actions == ['press:right', 'press:down'] and up['next_agent'] == 'verifier'


# ---------------------------------------------------------------- typist

def test_typist_retries_on_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('search'))
    reads = ['astr', 'astro bot']
    monkeypatch.setattr(typist.ocr, 'read_text', lambda f, region=None: reads.pop(0))
    state, ctx, rig = make(tmp_path)
    state = _with_plan(state, parse_step({'type': 'Astro Bot'}, 0))
    up = TypistAgent().run(state, ctx)
    assert rig.actions == ['type:Astro Bot'] + ['press:square'] * 6 + ['type:Astro Bot']
    assert up['next_agent'] == 'verifier' and up['plan'][0].reason == ''


def test_typist_match_no_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('search'))
    monkeypatch.setattr(typist.ocr, 'read_text', lambda f, region=None: 'astro bot')
    state, ctx, rig = make(tmp_path)
    state = _with_plan(state, parse_step({'type': 'AstroBot'}, 0))
    TypistAgent().run(state, ctx)
    assert rig.actions == ['type:AstroBot']


# ---------------------------------------------------------------- verifier

def test_check_expectation_rules() -> None:
    ok = scr('home', 'games media playstation plus', frame_path='a.jpg')
    assert check_expectation(Expectation(screen='home'), None, ok)[0] == Verdict.PASS
    assert check_expectation(Expectation(screen='search'), None, ok)[0] == Verdict.FAIL
    assert check_expectation(Expectation(text_contains=['playstatoin plus']), None, ok)[0] == Verdict.PASS
    assert check_expectation(Expectation(text_contains=['settings']), None, ok)[0] == Verdict.FAIL
    assert check_expectation(Expectation(text_absent=['media']), None, ok)[0] == Verdict.FAIL
    nof = scr('home', 'games')
    assert check_expectation(Expectation(screen='home'), None, nof)[0] == Verdict.BLOCKED
    assert check_expectation(Expectation(), None, nof)[0] == Verdict.BLOCKED
    blank = ScreenState(frame_path='b.jpg', blank=True)
    assert check_expectation(Expectation(screen='home'), None, blank)[0] == Verdict.BLOCKED
    v, why = check_expectation(Expectation(vision='search results shown'), None, ok, [frame(1)])
    assert v == Verdict.BLOCKED and 'LLM' in why
    assert check_expectation(Expectation(screen_changed=True), None, ok)[0] == Verdict.BLOCKED
    assert check_expectation(Expectation(screen_changed=True), None, ok,
                             [frame(10), frame(90)])[0] == Verdict.PASS
    assert check_expectation(Expectation(screen_changed=True), None, ok,
                             [frame(10), frame(10)])[0] == Verdict.FAIL


def test_check_expectation_vision_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    from ps5agent.perception import vision
    monkeypatch.setattr(llm, 'available', lambda: True)
    monkeypatch.setattr(vision, 'judge', lambda f, c: {'holds': False, 'confidence': 0.8, 'reason': 'no'})
    ok = scr('home', frame_path='a.jpg')
    assert check_expectation(Expectation(vision='x'), None, ok, [frame(1)])[0] == Verdict.FAIL


def test_verifier_pass_advances_then_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('home', 'games media'))
    state, ctx, _ = make(tmp_path)
    s1 = Step(id='a', goal='home', expect=Expectation(screen='home'))
    s2 = Step(id='b', goal='type', agent='typist', expect=Expectation(text_contains=['games']))
    state = _with_plan(state, s1, s2)
    up = VerifierAgent().run(state, ctx)
    assert up['plan'][0].verdict == Verdict.PASS and up['cursor'] == 1 and up['next_agent'] == 'typist'
    assert up['plan'][0].evidence
    up2 = VerifierAgent().run(merged(state, up), ctx)
    assert up2['verdict'] == Verdict.PASS and up2['next_agent'] == 'reporter'


def test_verifier_fail_routes_to_recovery_then_final_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('home'))
    state, ctx, _ = make(tmp_path)
    step = Step(id='a', goal='search', expect=Expectation(screen='search'), attempts=1)
    up = VerifierAgent().run(_with_plan(state, step), ctx)
    assert up['plan'][0].verdict == Verdict.FAIL and up['next_agent'] == 'recovery'
    up2 = VerifierAgent().run(_with_plan(state, step, replans=1), ctx)
    assert up2['verdict'] == Verdict.FAIL and up2['next_agent'] == 'reporter'


def test_verifier_no_frame_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('home'))
    state, ctx, rig = make(tmp_path)
    monkeypatch.setattr(rig, 'grab', lambda: None)
    s1 = Step(id='a', goal='home', expect=Expectation(screen='home'))
    s2 = Step(id='b', goal='more')
    up = VerifierAgent().run(_with_plan(state, s1, s2), ctx)
    assert up['verdict'] == Verdict.BLOCKED and up['next_agent'] == 'reporter'
    assert up['plan'][1].verdict == Verdict.SKIPPED


# ---------------------------------------------------------------- recovery

def test_recovery_reaches_home_and_replans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'), scr('unknown'), scr('home'))
    state, ctx, rig = make(tmp_path)
    step = Step(id='a', goal='x', verdict=Verdict.FAIL, reason='wrong screen')
    up = RecoveryAgent().run(_with_plan(state, step), ctx)
    assert rig.actions == ['press:circle', 'press:circle']
    assert up['next_agent'] == 'planner' and up['replans'] == 1 and up['recoveries'] == 1
    assert up['plan'][0].verdict == Verdict.PENDING


def test_recovery_danger_then_open_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('store', extras={'danger': 'store'}), scr('unknown'))
    state, ctx, rig = make(tmp_path, fr=frames(20))
    up = RecoveryAgent().run(_with_plan(state, Step(id='a', goal='x')), ctx)
    assert rig.actions == ['press:circle'] * 2 + ['press:circle'] * 3 + ['macro:open_home', 'macro:home_from_game']
    assert up['next_agent'] == 'planner'


def test_recovery_replan_budget_exhausted_goes_verifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('home'))
    state, ctx, rig = make(tmp_path)
    up = RecoveryAgent().run(_with_plan(state, Step(id='a', goal='x'), replans=1), ctx)
    assert rig.actions == [] and up['next_agent'] == 'verifier'
    assert up['plan'][0].verdict == Verdict.FAIL
    fin = VerifierAgent().run(merged(_with_plan(state, Step(id='a', goal='x'), replans=1), up), ctx)
    assert fin['verdict'] == Verdict.FAIL and fin['next_agent'] == 'reporter'


def test_recovery_escalates_to_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'))
    state, ctx, rig = make(tmp_path)
    up = RecoveryAgent().run(_with_plan(state, Step(id='a', goal='x'), recoveries=3), ctx)
    assert up['verdict'] == Verdict.BLOCKED and up['next_agent'] == 'reporter'
    assert up['recoveries'] == 4 and rig.actions == []


def test_recovery_dead_input_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'))
    state, ctx, rig = make(tmp_path, fr=[frame(70)])
    up = RecoveryAgent().run(_with_plan(state, Step(id='a', goal='x')), ctx)
    assert up['verdict'] == Verdict.BLOCKED and 'dead_input' in up['verdict_reason']
    assert len(rig.actions) == 3


# ---------------------------------------------------------------- gameplay

PROFILE = {'name': 'Fake Fighter',
           'combos': {'uppercut': [{'press': 'down'}, {'press': 'square'}],
                      'dash': [{'stick': 'left_stick', 'direction': 'right', 'duration': 0.3}]},
           'hud': {'p1_health': {'x': 0.0, 'y': 0.0, 'width': 0.5, 'height': 0.2}},
           'action_space': {'punch': [{'press': 'square'}], 'block': [{'hold': 'r2', 'duration': 0.5}],
                            'walk': [{'stick': 'left_stick', 'direction': 'right', 'duration': 0.3}]}}


def test_gameplay_scripted_combos_and_hud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'))
    sc = Scenario(id='g', goal='combos', type='gameplay_scripted', game='fake')
    state, ctx, rig = make(tmp_path, sc, profile=PROFILE)
    plan = PlannerAgent().run(state, ctx)['plan']
    assert [a.name for a in plan[0].actions] == ['combo:uppercut', 'combo:dash']
    up = GameplayAgent().run(_with_plan(state, *plan), ctx)
    assert rig.actions == ['press:down', 'press:square', 'stick:left_stick:right']
    gm = up['metrics']['gameplay']
    assert gm['counts'] == {'uppercut': 1, 'dash': 1} and gm['mode'] == 'scripted'
    assert gm['hud']['p1_health'] > 0 and up['next_agent'] == 'verifier'


def test_gameplay_unknown_combo_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'))
    state, ctx, _ = make(tmp_path, profile=PROFILE)
    up = GameplayAgent().run(_with_plan(state, parse_step({'combo': 'fatality'}, 0)), ctx)
    assert up['verdict'] == Verdict.BLOCKED and up['next_agent'] == 'reporter'


def test_gameplay_explore_random_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'))
    sc = Scenario(id='g', goal='fight', type='gameplay_explore', game='fake',
                  limits={'explore_ticks': 6, 'explore_seconds': 60})
    state, ctx, rig = make(tmp_path, sc, fr=[frame(50)], profile=PROFILE)
    step = Step(id='g1', goal='explore: fight', agent='gameplay')
    up = GameplayAgent(seed=7).run(_with_plan(state, step), ctx)
    gm = up['metrics']['gameplay']
    assert gm['policy'] == 'random' and gm['ticks'] == 6 and sum(gm['counts'].values()) == 6
    assert set(gm['counts']) <= set(PROFILE['action_space'])
    assert len(rig.actions) == 6 and up['next_agent'] == 'verifier'   # no dead_input in fights
    assert any('random policy' in n for n in up['notes'])


def test_gameplay_explore_llm_stops_on_round_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, scr('unknown'))
    monkeypatch.setattr(llm, 'available', lambda: True)
    replies = [{'action': 'punch', 'situation': {}}, {'action': 'block', 'situation': {}},
               {'action': 'punch', 'situation': {'round_over': True}}]
    monkeypatch.setattr(llm, 'ask', lambda *a, **k: replies.pop(0))
    sc = Scenario(id='g', goal='fight', type='gameplay_explore', limits={'explore_ticks': 10})
    state, ctx, rig = make(tmp_path, sc, profile=PROFILE)
    up = GameplayAgent().run(_with_plan(state, Step(id='g1', goal='fight', agent='gameplay')), ctx)
    gm = up['metrics']['gameplay']
    assert gm['counts'] == {'punch': 1, 'block': 1} and gm['stopped'] == 'round_over'
    assert rig.actions == ['press:square', 'hold:r2']


def test_hud_diff_regions() -> None:
    a, b = frame(10), frame(10)
    b[0:20, 0:240] = 200
    d = hud_diff(a, b, {'left': {'x': 0, 'y': 0, 'width': 0.5, 'height': 0.1},
                        'right': {'x': 0.5, 'y': 0.5, 'width': 0.5, 'height': 0.5}})
    assert d['left'] > 50 and d['right'] == 0.0


def test_llm_budget_exhausted_means_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, 'available', lambda: True)
    monkeypatch.setattr(llm, 'snapshot_metrics', lambda: {'calls': 5})
    assert base.llm_ok(FakeSettings(tmp_path, **{'llm.max_calls_per_run': 5})) is False
    assert base.llm_ok(FakeSettings(tmp_path, **{'llm.max_calls_per_run': 6})) is True


def test_parse_action_tolerates_llm_quirks() -> None:
    from ps5agent.agents.planner import parse_action
    assert parse_action({'kind': 'wait', 'name': 3.0}).duration == 3.0
    assert parse_action({'kind': 'wait', 'duration': None}).duration == 1.0
    assert parse_action({'kind': 'press', 'name': 'Cross', 'times': '2'}).times == 2
