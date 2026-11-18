'''Every scenario/suite YAML must load and reference real screens/agents/files.

Replays are data-driven: tests/replays/<scenario_id>.yaml gives the screen text the
rig should show after each action and the expected outcome, so this file holds no
game- or scenario-specific knowledge. See tests/replays/README.md.
'''

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ps5agent.agents import base
from ps5agent.agents.base import load_game_profile
from ps5agent.agents.planner import parse_action
from ps5agent.cli import load_scenario
from ps5agent.core import llm
from ps5agent.core.macros import is_known
from ps5agent.core.state import Verdict
from ps5agent.perception import ocr
from ps5agent.safety import action_gate as ag

ROOT = Path(__file__).parents[1]
FRAMES = Path(__file__).parent / 'fixtures' / 'frames'
SCREENS = {p.stem for p in (ROOT / 'config' / 'screens').glob('*.yaml')}
SCENARIOS = sorted((ROOT / 'scenarios').rglob('*.yaml'))
SUITES = sorted((ROOT / 'suites').glob('*.yaml'))
GAMES = sorted(p.parent for p in (ROOT / 'config' / 'games').glob('*/profile.yaml'))
REPLAYS = sorted((Path(__file__).parent / 'replays').glob('*.yaml'))
AGENTS = {'navigator', 'typist', 'gameplay', 'verifier', 'recovery'}


def _expects(sc) -> list[dict]:
    out = list(sc.expect)
    for st in sc.steps:
        e = st.get('expect') or {}
        out.extend(e if isinstance(e, list) else [e])
    return out


@pytest.mark.parametrize('path', SCENARIOS, ids=lambda p: p.stem)
def _game_screens(game: str | None) -> set[str]:
    d = ROOT / 'config' / 'games' / str(game) / 'screens'
    return {p.stem for p in d.glob('*.yaml')} if game and d.is_dir() else set()


def _check_action(raw, profile) -> None:
    a = parse_action(raw)
    if a.kind == 'macro' and not a.name.startswith('combo:'):
        assert is_known(a.name, profile), f'unknown macro {a.name!r} (controls.yaml / game profile)'


@pytest.mark.parametrize('path', SCENARIOS, ids=lambda p: p.stem)
def test_scenario_is_valid(path: Path) -> None:
    sc = load_scenario(path)
    assert sc.id == path.stem, 'scenario id must match its file name'
    assert sc.goal.strip()
    profile = None
    if sc.game:
        profile = load_game_profile(sc.game)
        assert profile is not None, f'missing config/games/{sc.game}/profile.yaml'
    known = SCREENS | _game_screens(sc.game)
    for e in _expects(sc):
        if e.get('screen'):
            assert e['screen'] in known, f"unknown screen {e['screen']!r} (config/screens/ or game screens)"
    ids = [st.get('id') for st in sc.steps]
    assert len(ids) == len(set(ids)), 'duplicate step ids'
    for st in sc.steps:
        assert st.get('agent', 'navigator') in AGENTS
        for a in st.get('actions') or []:
            _check_action(a, profile)
    for a in [*sc.setup, *sc.teardown, *sc.hints]:
        _check_action(a, profile)


@pytest.mark.parametrize('game_dir', GAMES, ids=lambda p: p.name)
def test_game_profile_is_valid(game_dir: Path) -> None:
    prof = load_game_profile(game_dir.name)
    assert isinstance(prof, dict) and prof.get('id') == game_dir.name, 'profile id must match folder'
    for spec in (prof.get('macros') or {}).values():
        for a in (spec.get('steps') if isinstance(spec, dict) else spec) or []:
            parse_action(a)
    for name in ('combos', 'moves', 'action_space'):
        block = prof.get(name) or {}
        for seq in (block.values() if isinstance(block, dict) else []):
            for a in (seq if isinstance(seq, list) else [seq]):
                if isinstance(a, dict):
                    parse_action(a)
    gate = prof.get('hud_gate')
    if gate:
        assert (prof.get('hud') or {}).get(gate, {}).get('type') == 'presence', \
            'hud_gate must name a presence check in hud'
    for f in (game_dir / 'screens').glob('*.yaml') if (game_dir / 'screens').is_dir() else []:
        data = yaml.safe_load(f.read_text(encoding='utf-8'))
        assert data.get('id') == f.stem, f'{f.name}: id must match file name'


@pytest.mark.parametrize('path', SUITES, ids=lambda p: p.stem)
def test_suite_references_exist(path: Path) -> None:
    suite = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert suite['name'] == path.stem and suite['scenarios']
    for rel in suite['scenarios']:
        assert (ROOT / rel).is_file(), f'{path.name}: missing {rel}'


# ---------------------------------------------------------------- data-driven replays

def _replay(spec: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    '''Run spec['scenario'] through the full graph on FakeRig.

    Frame k is shown after action k (frame 0 = start). Each frame gets a unique grey
    level so consecutive frames differ (no dead_input); OCR is replaced by a lookup
    from that level to the spec's screen text, so the REAL signature classifier,
    verifier and typist judge every frame.
    '''
    import numpy as np
    from ps5agent.graph import build as build_mod
    from ps5agent.hw import adapters
    from ps5agent.hw.adapters import FakeRig

    frames, text_of = [], {}
    for k, name in enumerate(spec['frames']):
        v = 20 + 9 * k
        assert v < 250, 'too many frames for the synthetic grey-level encoding'
        f = np.full((270, 480, 3), v, np.uint8)
        f[:, :120] = 255 - v                 # contrast so the frame is not blank
        frames.append(f)
        text_of[v] = spec['screens'][name]

    def read_text(f, region=None):
        px = int(f[0, -1, 0])
        return text_of[min(text_of, key=lambda v: abs(v - px))]

    monkeypatch.setattr(ocr, 'read_text', read_text)
    monkeypatch.setattr(llm, 'available', lambda: False)
    monkeypatch.setattr(base, 'SETTLE_OVERRIDE', 0.0)
    monkeypatch.setattr(ag, 'MIN_INTERVAL', 0.0)
    monkeypatch.setattr(build_mod.time, 'sleep', lambda s: None)
    monkeypatch.setattr(adapters.time, 'sleep', lambda s: None)
    monkeypatch.setattr(build_mod, 'new_run_dir', lambda sc, s=None: (tmp_path.name, tmp_path))
    rig = FakeRig(frames=frames)
    st = build_mod.run_scenario(load_scenario(ROOT / spec['scenario']), rig, checkpoint=False)
    return st, rig


def _cases() -> list[tuple[str, dict, dict]]:
    out = []
    for path in REPLAYS:
        spec = yaml.safe_load(path.read_text(encoding='utf-8'))
        for case in spec.get('cases') or []:
            out.append((f"{path.stem}-{case['name']}", spec, case))
    return out


CASES = _cases()


@pytest.mark.parametrize('spec', [yaml.safe_load(p.read_text(encoding='utf-8')) for p in REPLAYS],
                         ids=[p.stem for p in REPLAYS])
def test_replay_spec_is_valid(spec: dict) -> None:
    assert (ROOT / spec['scenario']).is_file(), spec['scenario']
    assert spec.get('cases'), 'replay spec needs at least one case'
    for case in spec['cases']:
        assert set(case['frames']) <= set(spec['screens']), 'frame names must be listed in screens'


@pytest.mark.parametrize('case_id,spec,case', CASES, ids=[c[0] for c in CASES])
def test_replay(case_id: str, spec: dict, case: dict, tmp_path: Path,
                monkeypatch: pytest.MonkeyPatch) -> None:
    st, rig = _replay({**spec, 'frames': case['frames']}, tmp_path, monkeypatch)
    want = Verdict(case.get('verdict', 'PASS'))
    if want == Verdict.PASS:
        assert st.verdict == Verdict.PASS, st.verdict_reason
    else:
        assert st.verdict != Verdict.PASS, 'scenario passed but the case expects it not to'
    if case.get('steps'):
        assert [s.id for s in st.plan] == case['steps']
    for sid, v in (case.get('step_verdicts') or {}).items():
        got = next(s for s in st.plan if s.id == sid).verdict
        assert (got == Verdict.PASS) == (Verdict(v) == Verdict.PASS), f'{sid}: {got}'
    skip = int(case.get('skip_actions', 0))
    tail = rig.actions[skip:]
    pos = [tail.index(a) for a in case.get('actions') or []]
    assert pos == sorted(pos), rig.actions
    assert (tmp_path / 'report.html').is_file()
