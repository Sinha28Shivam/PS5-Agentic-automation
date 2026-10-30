'''Perception tests on real PS5 reference frames (no hardware, no LLM unless RUN_LLM_TESTS=1).'''

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from ps5agent.core import llm
from ps5agent.core.evidence import Evidence
from ps5agent.perception import ocr, signatures, vision
from ps5agent.perception.perceive import Perception, changed, frozen

REF = Path(__file__).resolve().parents[2] / 'PS5-Automation-Python' / 'docs' / 'reference'
needs_ocr = pytest.mark.skipif(not ocr.available(), reason='tesseract not installed')
needs_llm = pytest.mark.skipif(os.environ.get('RUN_LLM_TESTS') != '1' or not llm.available(),
                               reason='set RUN_LLM_TESTS=1 (and ANTHROPIC_API_KEY)')

HOME_YAML = '''
id: home
description: PS5 home
any_text: ["games", "media", "recently played"]
all_text: ["console storage"]
none_text: ["search for games"]
min_score: 0.5
priority: 10
transitions: {circle: home}
'''
SEARCH_YAML = '''
id: search
any_text: ["search for games", "add-ons", "use your voice to search"]
all_text: []
min_score: 0.5
priority: 5
'''
NEVER_YAML = '''
id: settings
any_text: ["network", "accessibility"]
all_text: ["system software"]
min_score: 0.6
'''


LEGACY_YAML = '''
store: ["playstation store"]
account_prompt: ["sign in to playstation network"]
home: ["games"]
in_game: []
'''


def _img(name: str) -> np.ndarray:
    path = REF / name
    if not path.is_file():
        pytest.skip(f'missing reference frame {path}')
    img = cv2.imread(str(path))
    assert img is not None
    return img


@pytest.fixture
def screens_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / 'screens'
    d.mkdir()
    (d / 'home.yaml').write_text(HOME_YAML, encoding='utf-8')
    (d / 'search.yaml').write_text(SEARCH_YAML, encoding='utf-8')
    (d / 'settings.yaml').write_text(NEVER_YAML, encoding='utf-8')
    monkeypatch.setattr(signatures, 'SCREENS_DIR', d)
    signatures.clear_cache()
    return d


@pytest.fixture
def legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / 'screen_signatures.yaml'
    p.write_text(LEGACY_YAML, encoding='utf-8')
    monkeypatch.setattr(signatures, 'LEGACY_PATH', p)
    signatures.clear_cache()
    return p


# ---------------------------------------------------------------- OCR

@needs_ocr
def test_ocr_home_words() -> None:
    text = ocr.read_text(_img('ps5-home-1080p.png'))
    assert text == text.lower() and '  ' not in text
    for word in ('games', 'media', 'console storage', 'recently played', 'mortal kombat'):
        assert word in text, word


@needs_ocr
def test_ocr_search_words() -> None:
    text = ocr.read_text(_img('ps5-search.png'))
    assert 'search for games' in text
    assert 'add-ons' in text
    assert 'playstation plus' in text


@needs_ocr
def test_ocr_keyboard_crops() -> None:
    assert 'done' in ocr.read_text(_img('ps5-keyboard-abc.png'))
    shift = ocr.read_text(_img('ps5-keyboard-abc-shift.png'))
    assert 'games' in shift and 'add-ons' in shift


@needs_ocr
def test_ocr_region_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    img = _img('ps5-search.png')
    region = {'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 0.25}
    top = ocr.read_text(img, region=region)
    assert 'search for games' in top
    assert 'playstation plus' not in top
    monkeypatch.setattr(ocr.pytesseract, 'image_to_string',
                        lambda *a, **k: pytest.fail('cache miss'))
    assert ocr.read_text(img, region=dict(region)) == top


def test_crop_fractions() -> None:
    img = np.zeros((100, 200, 3), np.uint8)
    assert ocr.crop(img, {'x': 0.5, 'y': 0.5, 'width': 0.5, 'height': 0.5}).shape == (50, 100, 3)
    assert ocr.crop(img, None) is img


# ---------------------------------------------------------- signatures

def test_fuzzy_contains() -> None:
    assert signatures.fuzzy_contains('foo console storage bar', 'console storage')
    assert signatures.fuzzy_contains('consle storage', 'console storage')
    assert signatures.fuzzy_contains('storage x console', 'console storage')
    assert not signatures.fuzzy_contains('media games', 'console storage')
    assert not signatures.fuzzy_contains('megames', 'ps')


def test_match_synthetic(screens_dir: Path) -> None:
    loaded = signatures.load_screens()
    assert set(loaded) == {'home', 'search', 'settings'}
    assert loaded['home'].transitions == {'circle': 'home'}
    ranked = signatures.match('games media console storage recently played')
    assert ranked[0] == ('home', pytest.approx(1.0))
    assert signatures.match('games media') == []
    assert signatures.best('games console storage')[0] == 'home'
    assert signatures.match('games console storage search for games')[0][0] == 'search'
    assert signatures.best('nothing relevant here') is None


@needs_ocr
def test_match_reference_frames(screens_dir: Path) -> None:
    home = signatures.match(ocr.read_text(_img('ps5-home-1080p.png')))
    assert home and home[0][0] == 'home' and home[0][1] >= 0.5
    search = signatures.match(ocr.read_text(_img('ps5-search.png')))
    assert search and search[0][0] == 'search'
    assert 'home' not in dict(search)


def test_danger_screen_conservative(legacy: Path) -> None:
    assert signatures.danger_screen('games media playstation store console storage') is None
    assert signatures.danger_screen('playstation store add to cart rs 3,999') == 'store'
    assert signatures.danger_screen('playstation store purchase') == 'store'
    assert signatures.danger_screen('add to cart rs 3,999') is None
    assert signatures.danger_screen('playstation store buyer guide') is None
    assert signatures.danger_screen('please sign in to playstation network') == 'account_prompt'
    assert signatures.danger_screen('') is None


@needs_ocr
def test_danger_screen_real_frames(legacy: Path) -> None:
    assert signatures.danger_screen(ocr.read_text(_img('ps5-home-1080p.png'))) is None


# ---------------------------------------------------------- perceive

def test_blank_detection(screens_dir: Path) -> None:
    state = Perception().observe(np.full((720, 1280, 3), 3, np.uint8), use_vision='never')
    assert state.blank and state.source == 'none' and state.frame_hash


def test_frozen_and_changed() -> None:
    a = np.zeros((90, 160, 3), np.uint8)
    b = a.copy()
    b[:45] = 255
    assert frozen([a, a.copy(), a.copy()])
    assert not frozen([a, a, b])
    assert not frozen([a])
    moved, d = changed(a, b, 0.5)
    assert moved and d == pytest.approx(127.5)
    still, d0 = changed(a, a.copy(), 0.5)
    assert not still and d0 == 0.0
    assert changed(a, cv2.resize(b, (320, 180)), 0.5)[0]


@needs_ocr
def test_observe_signature_and_evidence(screens_dir: Path, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, 'available', lambda: False)
    p = Perception()
    img = _img('ps5-home-1080p.png')
    state = p.observe(img, evidence=Evidence(tmp_path / 'run'), tag='home')
    assert state.screen_id == 'home' and state.source == 'signature' and not state.blank
    assert state.frame_path and Path(state.frame_path).is_file()
    assert 'console storage' in state.text
    monkeypatch.setattr(ocr, 'read_text', lambda *a, **k: pytest.fail('cache miss'))
    again = p.observe(img)
    assert again.screen_id == 'home' and again.frame_path is None


def test_observe_vision_fallback(screens_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = np.random.default_rng(0).integers(0, 255, (90, 160, 3), dtype=np.uint8)
    monkeypatch.setattr(ocr, 'read_text', lambda *a, **k: 'lorem ipsum')
    monkeypatch.setattr(llm, 'available', lambda: True)
    seen: list[list[str]] = []

    def fake(f: np.ndarray, question: str | None = None, screens: list[str] | None = None) -> dict:
        seen.append(list(screens or []))
        return {'screen_id': 'search', 'description': 'search page', 'focused': 'search bar',
                'text_visible': [], 'dialog': False, 'in_game': False, 'confidence': 0.7}

    monkeypatch.setattr(vision, 'describe', fake)
    state = Perception().observe(frame)
    assert state.source == 'vision' and state.screen_id == 'search' and state.focused == 'search bar'
    assert set(seen[0]) == {'home', 'search', 'settings'}
    none = Perception().observe(frame, use_vision='never')
    assert none.source == 'none' and none.screen_id == 'unknown'


def test_vision_unavailable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise llm.LLMUnavailable('no key')
    monkeypatch.setattr(llm, 'ask', boom)
    frame = np.zeros((10, 10, 3), np.uint8)
    assert vision.describe(frame, screens=['home']) is None
    assert vision.judge([frame, frame], 'home is shown') is None


@needs_llm
def test_vision_describe_live() -> None:
    out = vision.describe(_img('ps5-home-1080p.png'), screens=['home', 'search'])
    assert out is not None and out['screen_id'] == 'home'


@needs_llm
def test_vision_judge_live() -> None:
    out = vision.judge([_img('ps5-home-1080p.png'), _img('ps5-search.png')],
                       'the search screen is open')
    assert out is not None and out['holds'] is True
