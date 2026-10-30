'''Text signatures: config/screens/*.yaml screen definitions + legacy danger lists.'''

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ..core.settings import get_settings, load_yaml

SCREENS_DIR: Path | None = None      # override (tests); default <config_dir>/screens
LEGACY_PATH: Path | None = None      # override (tests); default <config_dir>/screen_signatures.yaml
FUZZY_RATIO = 0.85
PURCHASE_WORDS = ('purchase', 'add to cart', 'buy', 'buy now', 'pre-order', 'preorder', 'checkout',
                  'confirm purchase', 'proceed to checkout')
_PRICE = re.compile(r'(?:rs\.?|inr|\$|usd|eur|gbp)\s?\d')


@dataclass
class Screen:
    id: str
    description: str = ''
    any_text: list[str] = field(default_factory=list)
    all_text: list[str] = field(default_factory=list)
    none_text: list[str] = field(default_factory=list)
    regions: dict[str, dict[str, float]] = field(default_factory=dict)
    min_score: float = 0.5
    priority: int = 0
    transitions: dict[str, str] = field(default_factory=dict)
    dismiss: str = ''          # button that safely closes this screen (modals/dialogs)
    danger: str = ''           # e.g. power / layout / store -> ActionGate lockdown

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Screen:
        low = lambda xs: [_norm(str(x)) for x in (xs or []) if str(x).strip()]
        return cls(id=str(d['id']), description=str(d.get('description') or ''),
                   any_text=low(d.get('any_text')), all_text=low(d.get('all_text')),
                   none_text=low(d.get('none_text')), regions=dict(d.get('regions') or {}),
                   min_score=float(d.get('min_score', 0.5)), priority=int(d.get('priority', 0)),
                   transitions={str(k): str(v) for k, v in (d.get('transitions') or {}).items()},
                   dismiss=str(d.get('dismiss') or ''), danger=str(d.get('danger') or ''))


_cache: dict[tuple[Any, ...], Any] = {}


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().lower()


def _words(text: str) -> list[str]:
    return re.findall(r'[a-z0-9]+(?:[-'+chr(39)+'][a-z0-9]+)*', text.lower())


def fuzzy_contains(text: str, phrase: str, ratio: float = FUZZY_RATIO) -> bool:
    '''True if phrase is (approximately) present in OCR text.'''
    text, phrase = _norm(text), _norm(phrase)
    if not phrase:
        return True
    if phrase in text:
        return True
    pw, tw = _words(phrase), _words(text)
    if not pw or not tw:
        return False
    if len(pw) > 1 and all(w in tw for w in pw):
        return True
    if len(phrase) < 4:
        return phrase in tw
    target = ' '.join(pw)
    n = len(pw)
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(len(tw) - size + 1):
            window = ' '.join(tw[i:i + size])
            if abs(len(window) - len(target)) > max(2, len(target) // 4):
                continue
            if SequenceMatcher(None, window, target).ratio() >= ratio:
                return True
    return False


def screens_dir() -> Path:
    return SCREENS_DIR if SCREENS_DIR is not None else get_settings().config_dir / 'screens'


def load_screens(directory: Path | None = None) -> dict[str, Screen]:
    '''Load every *.yaml in the screens dir (reloaded when files change).'''
    d = Path(directory or screens_dir())
    files = sorted(d.glob('*.yaml')) + sorted(d.glob('*.yml')) if d.is_dir() else []
    key = ('screens', str(d), tuple((str(f), f.stat().st_mtime_ns) for f in files))
    if key not in _cache:
        out: dict[str, Screen] = {}
        for f in files:
            data = load_yaml(f)
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict) and item.get('id'):
                    s = Screen.from_dict(item)
                    out[s.id] = s
        _cache[key] = out
    return _cache[key]


def score(screen: Screen, text: str) -> float:
    if not screen.any_text and not screen.all_text:
        return 0.0
    if any(fuzzy_contains(text, p) for p in screen.none_text):
        return 0.0
    all_frac = (sum(fuzzy_contains(text, p) for p in screen.all_text) / len(screen.all_text)
                if screen.all_text else 1.0)
    if not screen.any_text:
        return round(all_frac, 3)
    hits = sum(fuzzy_contains(text, p) for p in screen.any_text)
    if hits == 0:
        return 0.0
    return round(all_frac * (0.8 + 0.2 * hits / len(screen.any_text)), 3)


def match(text: str, screens: dict[str, Screen] | None = None) -> list[tuple[str, float]]:
    '''[(screen_id, score)] for screens with score > 0, best first (priority breaks ties).'''
    screens = load_screens() if screens is None else screens
    scored = [(s, score(s, text)) for s in screens.values()]
    scored = [x for x in scored if x[1] > 0]
    scored.sort(key=lambda x: (x[1], x[0].priority), reverse=True)
    return [(s.id, sc) for s, sc in scored]


def best(text: str, screens: dict[str, Screen] | None = None) -> tuple[str, float] | None:
    '''Best match that clears its own min_score, else None.'''
    screens = load_screens() if screens is None else screens
    for sid, sc in match(text, screens):
        if sc >= screens[sid].min_score:
            return sid, sc
    return None


def legacy_signatures() -> dict[str, Any]:
    p = Path(LEGACY_PATH or get_settings().config_dir / 'screen_signatures.yaml')
    if not p.is_file():
        return {}
    key = ('legacy', str(p), p.stat().st_mtime_ns)
    if key not in _cache:
        data = load_yaml(p) or {}
        _cache[key] = {k: [_norm(str(x)) for x in (data.get(k) or []) if str(x).strip()]
                       for k in ('store', 'account_prompt', 'home', 'in_game')}
    return _cache[key]


def _has_word(text: str, phrase: str) -> bool:
    return re.search(r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])', text) is not None


def purchase_cue(text: str) -> bool:
    t = _norm(text)
    if any(_has_word(t, w) for w in PURCHASE_WORDS):
        return True
    return 'cart' in _words(t) and _PRICE.search(t) is not None


def danger_screen(text: str) -> str | None:
    '''store / account_prompt / None. 'store' needs a store phrase AND a purchase cue,
    because 'playstation store' is also a widget title on the home screen.'''
    t = _norm(text)
    sig = legacy_signatures()
    if any(fuzzy_contains(t, p) for p in sig.get('account_prompt', [])):
        return 'account_prompt'
    if any(fuzzy_contains(t, p) for p in sig.get('store', [])) and purchase_cue(t):
        return 'store'
    return None


def clear_cache() -> None:
    _cache.clear()
