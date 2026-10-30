'''Per-run report: result.json (state + summary) and a self-contained report.html.'''

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ps5agent.core.state import RunState, Verdict

TEMPLATES = Path(__file__).resolve().parent / 'templates'


def _fmt(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f'{value:.2f}'
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True,
                   trim_blocks=True, lstrip_blocks=True)
_env.filters['fmt'] = _fmt


def rel_path(path: str | None, run_dir: Path | str) -> str | None:
    '''Evidence path relative to run_dir with forward slashes (portable report links).'''
    if not path:
        return None
    base = Path(run_dir).resolve()
    p = Path(path)
    if not p.is_absolute():
        if (base / p).exists() or not p.exists():
            return p.as_posix()
        p = p.resolve()
    try:
        return Path(os.path.relpath(p, base)).as_posix()
    except ValueError:  # other drive on Windows
        return p.as_posix()


def summarize(state: RunState) -> dict[str, Any]:
    end = state.finished or time.time()
    steps: dict[str, int] = {v.value.lower(): 0 for v in Verdict}
    for s in state.plan:
        steps[s.verdict.value.lower()] += 1
    steps['total'] = len(state.plan)
    hist = state.history
    actions = {
        'total': len(hist),
        'sent': sum(r.allowed and r.sent_ok for r in hist),
        'blocked': sum(not r.allowed for r in hist),
        'send_failed': sum(r.allowed and not r.sent_ok for r in hist),
        'changed': sum(bool(r.changed) for r in hist),
    }
    return {
        'run_id': state.run_id,
        'scenario_id': state.scenario.id,
        'verdict': state.verdict.value,
        'reason': state.verdict_reason,
        'started': state.started,
        'finished': state.finished,
        'duration': round(end - state.started, 3),
        'steps': steps,
        'actions': actions,
        'replans': state.replans,
        'recoveries': state.recoveries,
        'steps_taken': state.steps_taken,
        'llm': dict(state.metrics.get('llm') or {}),
    }


def write_report(state: RunState, run_dir: Path | str) -> dict[str, str]:
    '''Write run_dir/result.json and run_dir/report.html. Returns their paths.'''
    out = Path(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(state)
    data = state.model_dump(mode='json')
    data['run_dir'] = '.'
    for rec in data['history']:
        for key in ('before_frame', 'after_frame'):
            rec[key] = rel_path(rec.get(key), out)
    for step in data['plan']:
        step['evidence'] = [p for p in (rel_path(e, out) for e in step['evidence']) if p]
    data['screen']['frame_path'] = rel_path(data['screen'].get('frame_path'), out)
    data['summary'] = summary
    json_path = out / 'result.json'
    json_path.write_text(json.dumps(data, indent=2, default=str), encoding='utf-8')

    actions = [{**rec, 'label': raw.action.label(), 'offset': raw.ts - state.started}
               for rec, raw in zip(data['history'], state.history)]
    metrics = {k: v for k, v in data['metrics'].items() if k != 'llm'}
    html = _env.get_template('report.html.j2').render(
        scenario=data['scenario'], summary=summary, health=data['health'], steps=data['plan'],
        actions=actions, notes=data['notes'], screen=data['screen'], llm=summary['llm'],
        metrics=metrics, run_id=state.run_id,
        started=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(state.started)),
        generated=time.strftime('%Y-%m-%d %H:%M:%S'))
    html_path = out / 'report.html'
    html_path.write_text(html, encoding='utf-8')
    return {'result_json': str(json_path), 'report_html': str(html_path)}
