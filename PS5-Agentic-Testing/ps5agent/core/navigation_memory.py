"""Versioned, local navigation strategies; never executable code or assertion edits."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from .settings import PKG_ROOT
from .state import Action, Expectation, RunState, ScreenState

BUTTONS = frozenset(('cross', 'circle', 'square', 'triangle', 'up', 'down', 'left',
                     'right', 'options', 'ps', 'l1', 'r1', 'l2', 'r2'))
MAX_ACTIONS = 12


def navigation_macro(name: str) -> bool:
    '''Any console macro from controls.yaml or the rig; game combos are not navigation.'''
    from .macros import is_known
    return not name.startswith('combo:') and is_known(name)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     separators=(',', ':')).encode()).hexdigest()


def contract(state: RunState) -> str:
    return digest({'scenario': state.scenario.model_dump(mode='json'), 'plan': [
        {k: s.model_dump(mode='json')[k] for k in
         ('id', 'goal', 'agent', 'actions', 'expect', 'max_attempts')} for s in state.plan]})


def meaningful(expect: Expectation) -> bool:
    # HUD predicates are not certified by this navigation-only learner.
    return not expect.hud and bool(expect.screen or expect.text_contains or
                                   expect.text_absent or expect.vision or
                                   expect.screen_changed is not None)


def known(screen: ScreenState, minimum: float = 0.8) -> bool:
    return bool(screen.screen_id and screen.screen_id.lower() != 'unknown' and
                screen.source in ('signature', 'vision') and not screen.blank and
                screen.confidence >= minimum and screen.frame_path and
                Path(screen.frame_path).is_file())


def safe_actions(raw: list[Any]) -> list[Action]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ACTIONS:
        raise ValueError('navigation sequence must contain 1..12 actions')
    result = []
    for item in raw:
        if isinstance(item, dict) and set(item) - set(Action.model_fields):
            raise ValueError('unknown action fields')
        a = item.model_copy(deep=True) if isinstance(item, Action) else Action.model_validate(item)
        if a.text is not None or a.direction is not None or a.value is not None:
            raise ValueError('typing/stick/trigger payloads cannot be learned')
        if not 1 <= a.times <= 5:
            raise ValueError('navigation repeats must be 1..5')
        for value, upper in ((a.duration, 5), (a.interval, 2)):
            if value is not None and (not math.isfinite(value) or not 0 < value <= upper):
                raise ValueError('navigation timing outside allowed range')
        if a.kind in ('press', 'hold'):
            if a.name not in BUTTONS:
                raise ValueError('unknown controller button')
        elif a.kind == 'macro':
            if not navigation_macro(a.name):
                raise ValueError('unsupported navigation macro')
        elif a.kind != 'wait' or a.name or a.times != 1:
            raise ValueError('only button, navigation macro and wait actions may be learned')
        result.append(a)
    return result


class NavigationMemory:
    """Append-only generations with transactional compare-and-swap promotion."""

    def __init__(self, path: Path, namespace: str):
        self.path, self.namespace = path, namespace
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('unsupported navigation memory schema')
            db.execute('''CREATE TABLE IF NOT EXISTS lessons (
                namespace TEXT NOT NULL, key TEXT NOT NULL, generation INTEGER NOT NULL,
                active INTEGER NOT NULL, actions TEXT NOT NULL, provenance TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(namespace, key, generation))''')
            db.execute('PRAGMA user_version=1')

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=5)

    def lookup(self, key: str) -> tuple[int, list[Action] | None]:
        with self.connect() as db:
            row = db.execute('''SELECT generation, active, actions FROM lessons
                WHERE namespace=? AND key=? ORDER BY generation DESC LIMIT 1''',
                             (self.namespace, key)).fetchone()
        if not row:
            return 0, None
        if row[0] < 1 or row[1] not in (0, 1):
            raise ValueError('invalid navigation memory record')
        return row[0], safe_actions(json.loads(row[2])) if row[1] else None

    def append(self, key: str, generation: int, actions: list[Action] | None,
               provenance: dict[str, Any]) -> str | None:
        if type(generation) is not int or generation < 0:
            raise ValueError('invalid navigation memory generation')
        payload = ([a.model_dump(mode='json') for a in safe_actions(actions)]
                   if actions is not None else [])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT MAX(generation) FROM lessons WHERE namespace=? AND key=?',
                                (self.namespace, key)).fetchone()[0] or 0
            if latest != generation:
                return None
            version = latest + 1
            db.execute('''INSERT INTO lessons(namespace,key,generation,active,actions,provenance)
                       VALUES (?,?,?,?,?,?)''', (self.namespace, key, version, int(bool(payload)),
                                                json.dumps(payload), json.dumps(provenance)))
        return f'{key}:{version}'

    def invalidate(self, key: str, generation: int, provenance: dict[str, Any]) -> str | None:
        return self.append(key, generation, None, provenance)


def build_memory(ctx: Any) -> NavigationMemory | None:
    from ..hw.adapters import FakeRig, Rig
    settings = ctx.settings
    if not settings.get('learning.enabled', False):
        return None
    if type(ctx.rig) not in (Rig, FakeRig):
        raise ValueError('learning disabled for unrecognised rig type')
    revision = str(settings.get('learning.environment_revision', '')).strip()
    if not revision:
        raise ValueError('learning.environment_revision is required')
    files = {}
    roots = [Path(settings.controls_config), Path(settings.config_dir),
             Path(settings.prompts_dir), PKG_ROOT / 'ps5agent']
    automation = getattr(settings, 'automation_root', None)
    if automation:
        roots.append(Path(automation))
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob('*')) if root.is_dir() else []
        for path in paths:
            if path.is_file() and path.suffix in ('.yaml', '.yml', '.py', '.txt', '.j2'):
                files[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    namespace = digest({'schema': 1, 'rig': type(ctx.rig).__name__,
                        'dry_run': bool(settings.get('runtime.dry_run', False)),
                        'revision': revision, 'settings': settings.data, 'files': files,
                        'profile': ctx.game_profile})
    path = Path(settings.get('learning.path', './artifacts/navigation-memory.sqlite3'))
    if not path.is_absolute():
        path = PKG_ROOT / path
    return NavigationMemory(path, namespace)


def context_key(state: RunState, screen: ScreenState, minimum: float = 0.8) -> str | None:
    step = state.current_step()
    if (not step or not meaningful(step.expect) or not known(screen, minimum) or
            state.learning_contract != contract(state)):
        return None
    return digest({'contract': state.learning_contract, 'step': step.id,
                   'screen': screen.screen_id, 'source': screen.source,
                   'text': screen.text, 'focused': screen.focused,
                   'description': screen.description, 'extras': screen.extras})
