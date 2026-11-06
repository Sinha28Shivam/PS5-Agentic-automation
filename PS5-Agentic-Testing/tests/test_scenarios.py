'''Every scenario/suite YAML must load and reference real screens/agents/files.

Also an end-to-end replay of home_navigation through the full graph on real PS5 frames.
Copy test_replay_home_navigation as the template when adding a new scenario test.
'''

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ps5agent.agents import base
from ps5agent.agents.planner import parse_action
from ps5agent.cli import load_scenario
from ps5agent.core import llm
from ps5agent.core.state import Verdict
from ps5agent.perception import ocr

ROOT = Path(__file__).parents[1]
FRAMES = Path(__file__).parent / 'fixtures' / 'frames'
SCREENS = {p.stem for p in (ROOT / 'config' / 'screens').glob('*.yaml')}
SCENARIOS = sorted((ROOT / 'scenarios').rglob('*.yaml'))
SUITES = sorted((ROOT / 'suites').glob('*.yaml'))
AGENTS = {'navigator', 'typist', 'gameplay', 'verifier', 'recovery'}


def _expects(sc) -> list[dict]:
    out = list(sc.expect)
    for st in sc.steps:
        e = st.get('expect') or {}
        out.extend(e if isinstance(e, list) else [e])
    return out


@pytest.mark.parametrize('path', SCENARIOS, ids=lambda p: p.stem)
def test_scenario_is_valid(path: Path) -> None:
    sc = load_scenario(path)
    assert sc.id == path.stem, 'scenario id must match its file name'
    assert sc.goal.strip()
    for e in _expects(sc):
        if e.get('screen'):
            assert e['screen'] in SCREENS, f"unknown screen {e['screen']!r} (config/screens/)"
    ids = [st.get('id') for st in sc.steps]
    assert len(ids) == len(set(ids)), 'duplicate step ids'
    for st in sc.steps:
        assert st.get('agent', 'navigator') in AGENTS
        for a in st.get('actions') or []:
            parse_action(a)
    for a in [*sc.setup, *sc.teardown, *sc.hints]:
        parse_action(a)


@pytest.mark.parametrize('path', SUITES, ids=lambda p: p.stem)
def test_suite_references_exist(path: Path) -> None:
    suite = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert suite['name'] == path.stem and suite['scenarios']
    for rel in suite['scenarios']:
        assert (ROOT / rel).is_file(), f'{path.name}: missing {rel}'


@pytest.mark.skipif(not ocr.available(), reason='tesseract missing')
def test_replay_home_navigation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    '''Full graph on real frames. FakeRig advances one frame per action:
    setup open_home, preflight open_home, ps probe, circle undo, r1, l1.'''
    from ps5agent.graph import build as build_mod
    from ps5agent.hw.adapters import FakeRig
    import cv2

    monkeypatch.setattr(llm, 'available', lambda: False)
    monkeypatch.setattr(base, 'SETTLE_OVERRIDE', 0.0)
    monkeypatch.setattr(build_mod.time, 'sleep', lambda s: None)
    monkeypatch.setattr(build_mod, 'new_run_dir', lambda sc, s=None: (tmp_path.name, tmp_path))
    seq = ['home', 'home', 'home', 'home_media', 'home', 'home_media', 'home']
    rig = FakeRig(frames=[cv2.imread(str(FRAMES / f'{n}.jpg')) for n in seq])
    st = build_mod.run_scenario(load_scenario(ROOT / 'scenarios/system_ui/home_navigation.yaml'),
                                rig, checkpoint=False)
    assert st.verdict == Verdict.PASS, st.verdict_reason
    assert [s.id for s in st.plan] == ['to_media', 'to_games']
    assert 'press:r1' in rig.actions and 'press:l1' in rig.actions
    assert (tmp_path / 'report.html').is_file()
