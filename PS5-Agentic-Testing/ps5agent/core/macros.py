"""Macro catalogue: every macro the rig can run, with a one-line description.

Sources (no game or scenario knowledge lives here):
  * `macros:` in the hardware layer's controls.yaml (console navigation macros)
  * rig-level macros implemented in ps5agent.hw.adapters (RIG_MACROS)
  * the active game profile's `macros:` block (named action sequences)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .settings import get_settings, load_yaml

# Implemented by hw.adapters.Rig.macro, not by controls.yaml. A key ending in
# ':' is a parameterised prefix.
RIG_MACROS = {
    'home_from_game': 'from inside a game: Control Center -> Home icon (guarded) -> PS5 Home',
    'focus_tile:': 'focus_tile:<caption_words>[:ps4|ps5] - Home game row: walk until the '
                   'focused tile caption contains the words (underscores = spaces)',
    'combo:': 'combo:<name> - a named move/combo from the game profile (gameplay agent)',
}
_FOCUS_TILE = re.compile(r'focus_tile:[^:\r\n]{1,100}(?::ps[45])?')

_cache: dict[tuple[str, int], dict[str, str]] = {}


def _first_line(text: Any) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:160]


def controls_macros(path: Path | str | None = None) -> dict[str, str]:
    p = Path(path or get_settings().controls_config)
    if not p.is_file():
        return {}
    key = (str(p), p.stat().st_mtime_ns)
    if key not in _cache:
        data = load_yaml(p) or {}
        _cache[key] = {str(k): _first_line((v or {}).get('description') if isinstance(v, dict) else '')
                       for k, v in (data.get('macros') or {}).items()}
    return _cache[key]


def catalogue(profile: dict[str, Any] | None = None, settings: Any = None) -> dict[str, str]:
    """name -> description for every macro available in this run."""
    path = getattr(settings, 'controls_config', None) if settings is not None else None
    out = dict(controls_macros(path))
    out.update(RIG_MACROS)
    for name, spec in ((profile or {}).get('macros') or {}).items():
        desc = spec.get('description', '') if isinstance(spec, dict) else ''
        out[str(name)] = _first_line(desc) or 'game profile macro'
    return out


def profile_macro(profile: dict[str, Any] | None, name: str) -> list[Any] | None:
    """Shorthand steps for a game-profile macro, or None if the profile has none."""
    spec = ((profile or {}).get('macros') or {}).get(name)
    if spec is None:
        return None
    steps = spec.get('steps') if isinstance(spec, dict) else spec
    return list(steps or [])


def is_known(name: str, profile: dict[str, Any] | None = None, settings: Any = None) -> bool:
    if _FOCUS_TILE.fullmatch(name):
        return True
    return name in catalogue(profile, settings) and not name.endswith(':')
