'''Suite report: suite.json, suite.html (links to each run report) and junit.xml for CI.'''

from __future__ import annotations

import html
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

COLORS = {'PASS': '#2ea043', 'FAIL': '#da3633', 'BLOCKED': '#d29922', 'SKIPPED': '#6e7681'}


def _rel(path: str | None, base: Path) -> str | None:
    if not path:
        return None
    try:
        return Path(os.path.relpath(Path(path).resolve(), base.resolve())).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def _norm(r: dict[str, Any], out: Path) -> dict[str, Any]:
    verdict = str(getattr(r.get('verdict'), 'value', r.get('verdict')) or 'BLOCKED').upper()
    run_dir = r.get('run_dir')
    report = None
    if run_dir:
        report = _rel(str(Path(run_dir) / 'report.html'), out)
    return {'scenario_id': str(r.get('scenario_id', '?')), 'verdict': verdict,
            'reason': str(r.get('reason') or ''), 'run_dir': str(run_dir) if run_dir else None,
            'report': report, 'duration': float(r.get('duration') or 0.0)}


def _junit(suite_name: str, rows: list[dict[str, Any]], counts: dict[str, int], total_time: float) -> ET.Element:
    attrs = {'name': suite_name, 'tests': str(len(rows)), 'failures': str(counts['FAIL']),
             'errors': str(counts['BLOCKED'] + counts['OTHER']), 'skipped': str(counts['SKIPPED']),
             'time': f'{total_time:.3f}', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')}
    root = ET.Element('testsuites', {k: attrs[k] for k in ('name', 'tests', 'failures', 'errors', 'skipped', 'time')})
    ts = ET.SubElement(root, 'testsuite', attrs)
    for r in rows:
        tc = ET.SubElement(ts, 'testcase', {'classname': suite_name, 'name': r['scenario_id'],
                                            'time': f"{r['duration']:.3f}"})
        v, msg = r['verdict'], r['reason'] or r['verdict']
        if v == 'FAIL':
            ET.SubElement(tc, 'failure', {'message': msg, 'type': 'FAIL'}).text = msg
        elif v == 'SKIPPED':
            ET.SubElement(tc, 'skipped', {'message': msg})
        elif v != 'PASS':
            ET.SubElement(tc, 'error', {'message': msg, 'type': v}).text = msg
        if r['run_dir']:
            ET.SubElement(tc, 'system-out').text = f"run_dir: {r['run_dir']}"
    return root


def _html(suite_name: str, rows: list[dict[str, Any]], counts: dict[str, int], total_time: float) -> str:
    e = html.escape
    body = []
    for r in rows:
        color = COLORS.get(r['verdict'], '#6e7681')
        link = f"<a href=\"{e(r['report'])}\">report</a>" if r['report'] else '-'
        body.append(f"<tr><td>{e(r['scenario_id'])}</td><td><span class=\"b\" style=\"background:{color}\">"
                    f"{e(r['verdict'])}</span></td><td>{e(r['reason'])}</td><td>{r['duration']:.1f}s</td><td>{link}</td></tr>")
    overall = 'PASS' if rows and counts['PASS'] == len(rows) - counts['SKIPPED'] else ('FAIL' if counts['FAIL'] else 'BLOCKED')
    chips = ' '.join(f"<span class=\"b\" style=\"background:{COLORS.get(k, '#6e7681')}\">{k} {counts[k]}</span>"
                     for k in ('PASS', 'FAIL', 'BLOCKED', 'SKIPPED'))
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{e(suite_name)} - {overall}</title>
<style>
body {{ margin:0; padding:24px; background:#111418; color:#e3e7ec; font:14px/1.45 "Segoe UI", sans-serif; }}
table {{ width:100%; border-collapse:collapse; background:#1b2027; border:1px solid #2c333d; margin-top:16px; }}
th, td {{ padding:7px 10px; border-bottom:1px solid #2c333d; text-align:left; }}
th {{ background:#222831; color:#8b95a3; font-size:12px; text-transform:uppercase; }}
.b {{ display:inline-block; padding:3px 9px; border-radius:4px; font-weight:600; font-size:12px; color:#fff; }}
a {{ color:#58a6ff; }} .dim {{ color:#8b95a3; }}
</style></head><body>
<h1>{e(suite_name)} <span class="b" style="background:{COLORS[overall]};font-size:18px">{overall}</span></h1>
<div>{chips} <span class="dim">&middot; {len(rows)} scenarios &middot; {total_time:.1f}s</span></div>
<table><tr><th>scenario</th><th>verdict</th><th>reason</th><th>duration</th><th>report</th></tr>
{chr(10).join(body)}
</table>
<p class="dim">generated {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>
'''


def write_suite_report(suite_name: str, results: list[dict[str, Any]], out_dir: Path | str) -> dict[str, str]:
    '''results: [{scenario_id, verdict, reason, run_dir, duration}]. Returns paths of suite.json/html, junit.xml.'''
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [_norm(r, out) for r in results]
    counts = {k: 0 for k in ('PASS', 'FAIL', 'BLOCKED', 'SKIPPED', 'OTHER')}
    for r in rows:
        counts[r['verdict'] if r['verdict'] in counts else 'OTHER'] += 1
    total_time = sum(r['duration'] for r in rows)
    paths = {'suite_json': str(out / 'suite.json'), 'suite_html': str(out / 'suite.html'),
             'junit_xml': str(out / 'junit.xml')}
    summary = {'suite': suite_name, 'generated': time.time(), 'total': len(rows), 'duration': total_time,
               'counts': counts, 'results': rows}
    Path(paths['suite_json']).write_text(json.dumps(summary, indent=2), encoding='utf-8')
    Path(paths['suite_html']).write_text(_html(suite_name, rows, counts, total_time), encoding='utf-8')
    tree = ET.ElementTree(_junit(suite_name, rows, counts, total_time))
    ET.indent(tree)
    tree.write(paths['junit_xml'], encoding='utf-8', xml_declaration=True)
    return paths
