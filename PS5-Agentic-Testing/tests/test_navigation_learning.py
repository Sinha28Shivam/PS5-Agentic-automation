"""Offline cross-run navigation learning; no hardware or model calls."""
from pathlib import Path

import pytest

from test_agents import _offline, make, merged, scr, script
from ps5agent.agents import navigator
from ps5agent.agents.learning import finalize_learning, proof_error
from ps5agent.agents.navigator import NavigatorAgent
from ps5agent.agents.planner import PlannerAgent
from ps5agent.agents.verifier import VerifierAgent
from ps5agent.core.navigation_memory import NavigationMemory, contract
from ps5agent.core.state import Action, Scenario, Verdict
from ps5agent.reporting.report import write_report


def setup_run(tmp_path, db, name='day1', final=None):
    scenario = Scenario(id='navigation', goal='open search', steps=[{
        'id': 'search', 'goal': 'open search', 'actions': [{'press': 'right'}],
        'expect': {'screen': 'search'}, 'max_attempts': 3}], expect=final or [])
    state, ctx, rig = make(tmp_path / name, scenario, **{'learning.enabled': True})
    ctx.navigation_memory = NavigationMemory(db, 'offline-test')
    ctx.learning_error = ''
    state = merged(state, PlannerAgent().run(state, ctx))
    assert state.learning_contract
    return state, ctx, rig


def execute(state, ctx, monkeypatch, end='search'):
    script(monkeypatch, scr('home'), scr(end), scr(end))
    state = merged(state, NavigatorAgent().run(state, ctx))
    return merged(state, VerifierAgent().run(state, ctx))


def retry(state):
    state = state.model_copy(deep=True)
    state.cursor = 0
    state.plan[0].verdict = Verdict.PENDING
    state.verdict = Verdict.PENDING
    return state


def learn(tmp_path, monkeypatch, final=None):
    state, ctx, _ = setup_run(tmp_path, tmp_path / 'memory.sqlite3', final=final)
    state = execute(state, ctx, monkeypatch, 'home')
    assert state.plan[0].verdict == Verdict.FAIL
    assert state.navigation_attempts[0].verdict == Verdict.FAIL
    monkeypatch.setattr(navigator, 'ask_llm', lambda *a, **k: {'actions': [{'press': 'cross'}]})
    state = execute(retry(state), ctx, monkeypatch)
    return state, ctx


def test_learn_reuse_invalidate_and_replace_across_runs(tmp_path, monkeypatch):
    state, ctx = learn(tmp_path, monkeypatch)
    assert state.verdict == Verdict.PASS
    original_contract = state.learning_contract
    state = finalize_learning(state, ctx)
    correction = state.navigation_attempts[-1]
    assert correction.promoted_id
    assert state.navigation_attempts[0].verdict == Verdict.FAIL
    assert state.plan[0].actions == [Action(kind='press', name='right')]
    assert contract(state) == original_contract

    day2, ctx2, _ = setup_run(tmp_path, tmp_path / 'memory.sqlite3', 'day2')
    monkeypatch.setattr(navigator, 'ask_llm', lambda *a, **k: pytest.fail('reuse must not call model'))
    day2 = execute(day2, ctx2, monkeypatch, 'home')
    reused = day2.navigation_attempts[-1]
    assert reused.source == 'reused'
    assert reused.actions == correction.actions
    assert reused.invalidated_id
    assert ctx2.navigation_memory.lookup(reused.key)[1] is None

    monkeypatch.setattr(navigator, 'ask_llm', lambda *a, **k: {'actions': [{'press': 'down'}]})
    day2 = finalize_learning(execute(retry(day2), ctx2, monkeypatch), ctx2)
    assert day2.navigation_attempts[-1].promoted_id
    day3, ctx3, _ = setup_run(tmp_path, tmp_path / 'memory.sqlite3', 'day3')
    monkeypatch.setattr(navigator, 'ask_llm', lambda *a, **k: pytest.fail('reuse must not call model'))
    day3 = finalize_learning(execute(day3, ctx3, monkeypatch), ctx3)
    assert day3.verdict == Verdict.PASS
    assert day3.navigation_attempts[-1].source == 'reused'
    assert day3.navigation_attempts[-1].actions == [Action(kind='press', name='down')]


@pytest.mark.parametrize('final_screen', ['search', 'home'])
def test_original_final_assertions_gate_promotion(tmp_path, monkeypatch, final_screen):
    state, ctx = learn(tmp_path, monkeypatch, final=[{'screen': 'search'}])
    assert len(state.plan) == 2 and state.plan[-1].agent == 'verifier'
    assert not state.navigation_attempts[-1].promoted_id
    script(monkeypatch, scr(final_screen))
    state = merged(state, VerifierAgent().run(state, ctx))
    state = finalize_learning(state, ctx)
    assert bool(state.navigation_attempts[-1].promoted_id) == (final_screen == 'search')


@pytest.mark.parametrize('damage', ['skipped', 'unverified', 'contract', 'unsent', 'owner', 'partial', 'boundary', 'missing'])
def test_incomplete_proof_never_promotes(tmp_path, monkeypatch, damage):
    state, ctx = learn(tmp_path, monkeypatch)
    attempt = state.navigation_attempts[-1]
    if damage == 'skipped':
        state.plan[0].verdict = Verdict.SKIPPED
    elif damage == 'unverified':
        state.learning_verified.clear()
    elif damage == 'contract':
        state.plan[0].expect.screen = 'home'
    elif damage == 'unsent':
        state.history[-1].sent_ok = False
    elif damage == 'owner':
        state.history[-1].agent = 'recovery'
    elif damage == 'partial':
        attempt.actions.append(Action(kind='press', name='down'))
    elif damage == 'boundary':
        attempt.history_start = -1
    else:
        Path(state.history[-1].before_frame).unlink()
    state = finalize_learning(state, ctx)
    assert state.verdict == Verdict.BLOCKED
    assert not state.navigation_attempts[-1].promoted_id


def test_unknown_screen_cannot_pass_learning_verification(tmp_path, monkeypatch):
    state, ctx, _ = setup_run(tmp_path, tmp_path / 'memory.sqlite3')
    script(monkeypatch, scr(), scr('search'), scr('search', confidence=0.1))
    state = merged(state, NavigatorAgent().run(state, ctx))
    state = merged(state, VerifierAgent().run(state, ctx))
    assert state.verdict == Verdict.BLOCKED


def test_no_model_correction_and_contract_drift_stop(tmp_path, monkeypatch):
    state, ctx, _ = setup_run(tmp_path, tmp_path / 'memory.sqlite3')
    state = execute(state, ctx, monkeypatch, 'home')
    monkeypatch.setattr(navigator, 'ask_llm', lambda *a, **k: None)
    state = merged(retry(state), NavigatorAgent().run(retry(state), ctx))
    assert state.verdict == Verdict.BLOCKED
    assert 'no safe navigation' in state.verdict_reason
    state.plan[0].expect.screen = 'home'
    assert PlannerAgent().run(state, ctx)['verdict'] == Verdict.BLOCKED


def test_storage_errors_and_cas_conflicts_are_visible(tmp_path, monkeypatch):
    state, ctx = learn(tmp_path, monkeypatch)
    monkeypatch.setattr(ctx.navigation_memory, 'append', lambda *a: None)
    conflict = finalize_learning(state, ctx)
    assert 'conflict' in conflict.navigation_attempts[-1].memory_status
    assert not conflict.navigation_attempts[-1].promoted_id

    def fail(*args):
        raise OSError('storage unavailable')
    monkeypatch.setattr(ctx.navigation_memory, 'append', fail)
    failed = finalize_learning(state, ctx)
    assert ctx.navigation_memory is None
    assert 'navigation memory disabled: OSError' in failed.notes
    assert not failed.navigation_attempts[-1].promoted_id


def test_learning_report_retains_failures_and_portable_evidence(tmp_path, monkeypatch):
    import json
    state, ctx = learn(tmp_path, monkeypatch)
    state = finalize_learning(state, ctx)
    paths = write_report(state, ctx.evidence.dir)
    data = json.loads(Path(paths['result_json']).read_text())
    attempts = data['navigation_attempts']
    assert attempts[0]['verdict'] == 'FAIL'
    assert not Path(attempts[0]['start']['frame_path']).is_absolute()
    assert not Path(attempts[-1]['end']['frame_path']).is_absolute()
    assert all(not Path(p).is_absolute() for p in attempts[-1]['evidence'])
    html = Path(paths['report_html']).read_text(encoding='utf-8')
    assert 'Navigation learning' in html and 'promoted' in html
