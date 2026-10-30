"""Offline tests for ActionGate (FakeRig + synthetic frames, no hardware)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ps5agent.core.evidence import Evidence
from ps5agent.core.state import Action, Scenario, ScreenState
from ps5agent.hw.adapters import FakeRig
from ps5agent.safety import action_gate as ag
from ps5agent.safety.action_gate import ActionGate


class FakeSettings:
    def __init__(self, **over: Any):
        self.data = {"runtime.max_steps": 40, "runtime.dead_input_streak": 3,
                     "verification.screen_change_threshold": 0.5, **over}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def frame(v: int) -> np.ndarray:
    return np.full((270, 480, 3), v, np.uint8)


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ag, "MIN_INTERVAL", 0.0)


def make(tmp_path: Path, frames: list[np.ndarray] | None = None, allow: list[str] | None = None,
         limits: dict[str, Any] | None = None, **over: Any) -> tuple[ActionGate, FakeRig, Evidence]:
    rig = FakeRig(frames=frames or [frame(10)])
    ev = Evidence(tmp_path / "run")
    sc = Scenario(id="t", goal="g", allow=allow or [], limits=limits or {})
    return ActionGate(rig, ev, sc, FakeSettings(**over)), rig, ev


def press(name: str, reason: str = "") -> Action:
    return Action(kind="press", name=name, reason=reason)


def events(ev: Evidence) -> list[dict[str, Any]]:
    return [json.loads(l) for l in ev.log_path.read_text(encoding="utf-8").splitlines()]


def test_max_steps_from_scenario_limits(tmp_path: Path) -> None:
    gate, rig, _ = make(tmp_path, [frame(10), frame(200), frame(10)], limits={"max_steps": 2})
    s = ScreenState()
    assert gate.execute(press("right"), s, "nav", settle=0).allowed
    assert gate.execute(press("left"), s, "nav", settle=0).allowed
    rec = gate.execute(press("right"), s, "nav", settle=0)
    assert not rec.allowed and "max_steps" in rec.blocked_reason
    assert gate.steps == 2 and len(rig.actions) == 2


def test_max_steps_from_settings(tmp_path: Path) -> None:
    gate, _, _ = make(tmp_path, **{"runtime.max_steps": 1})
    gate._steps = 1
    ok, reason = gate.check(press("down"), ScreenState(), "nav")
    assert not ok and "max_steps" in reason


@pytest.mark.parametrize("danger", ["store", "account_prompt"])
def test_danger_denies_confirm_allows_escape(tmp_path: Path, danger: str) -> None:
    gate, _, _ = make(tmp_path)
    s = ScreenState(extras={"danger": danger})
    for a in (press("cross"), press("options"), press("r2"), Action(kind="type", text="x")):
        assert gate.check(a, s, "nav")[0] is False
    assert gate.check(press("circle"), s, "nav") == (True, "ok")
    assert gate.check(press("ps"), s, "nav") == (True, "ok")


def test_danger_store_allowed(tmp_path: Path) -> None:
    gate, _, _ = make(tmp_path, allow=["store"])
    assert gate.check(press("cross"), ScreenState(extras={"danger": "store"}), "nav")[0]


def test_destructive_focus_denied(tmp_path: Path) -> None:
    gate, rig, ev = make(tmp_path)
    s = ScreenState(screen_id="game_options", focused="Delete")
    rec = gate.execute(press("cross"), s, "nav", settle=0)
    assert not rec.allowed and "destructive" in rec.blocked_reason
    assert rig.actions == [] and events(ev)[-1]["event"] == "action_blocked"
    # navigating on the menu that contains Delete is fine
    assert gate.check(press("down"), s, "nav")[0]
    # screen text alone does not trigger the rule
    assert gate.check(press("cross"), ScreenState(text="delete", focused="information"), "n")[0]


def test_destructive_reason_denied(tmp_path: Path) -> None:
    gate, _, _ = make(tmp_path)
    assert not gate.check(press("cross", "factory reset console"), ScreenState(), "nav")[0]


def test_destructive_allowed(tmp_path: Path) -> None:
    gate, _, _ = make(tmp_path, allow=["destructive"])
    assert gate.check(press("cross"), ScreenState(focused="delete"), "nav") == (True, "ok")


def test_settings_cross_warns_not_blocks(tmp_path: Path) -> None:
    gate, _, ev = make(tmp_path)
    assert gate.check(press("cross"), ScreenState(screen_id="settings_sound"), "nav")[0]
    assert gate.notes and events(ev)[-1]["event"] == "settings_write_warning"


def test_dead_streak(tmp_path: Path) -> None:
    gate, _, _ = make(tmp_path, [frame(10)])
    s = ScreenState()
    for i in range(3):
        rec = gate.execute(press("down"), s, "nav", settle=0)
        assert rec.allowed and rec.changed is False
        assert gate.dead_streak == i + 1
    gate.execute(Action(kind="type", text="a"), s, "typist", settle=0)
    assert gate.dead_streak == 3
    rec = gate.execute(press("down"), s, "nav", settle=0)
    assert not rec.allowed and rec.blocked_reason == "dead_input"
    gate.reset_streak()
    assert gate.dead_streak == 0 and gate.check(press("down"), s, "nav")[0]


def test_change_resets_streak(tmp_path: Path) -> None:
    gate, _, _ = make(tmp_path, [frame(10), frame(10), frame(200)])
    s = ScreenState()
    gate.execute(press("down"), s, "nav", settle=0)
    assert gate.dead_streak == 1
    rec = gate.execute(press("down"), s, "nav", settle=0)
    assert rec.changed is True and gate.dead_streak == 0


def test_execute_saves_frames_and_changed(tmp_path: Path) -> None:
    gate, rig, ev = make(tmp_path, [frame(10), frame(200)])
    rec = gate.execute(press("cross"), ScreenState(), "nav", settle=0)
    assert rec.allowed and rec.sent_ok and rig.actions == ["press:cross"]
    assert rec.changed is True and rec.delta == pytest.approx(190.0)
    assert Path(rec.before_frame).is_file() and Path(rec.after_frame).is_file()
    assert "before" in rec.before_frame and "after" in rec.after_frame
    assert rec.before_hash != rec.after_hash
    ev_last = events(ev)[-1]
    assert ev_last["event"] == "action" and ev_last["changed"] is True
    rec2 = gate.execute(press("cross"), ScreenState(), "nav", settle=0)
    assert rec2.changed is False and rec2.delta == 0.0


def test_blank_grab_counts_dead(tmp_path: Path) -> None:
    gate, rig, _ = make(tmp_path)
    rig.grab = lambda: None  # type: ignore[method-assign]
    rec = gate.execute(press("down"), ScreenState(), "nav", settle=0)
    assert rec.allowed and rec.changed is None and rec.before_frame is None
    assert gate.dead_streak == 1


def test_rate_limit_sleeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ag, "MIN_INTERVAL", 0.15)
    gate, _, _ = make(tmp_path, [frame(10), frame(200), frame(10)])
    import time
    t = time.monotonic()
    gate.execute(press("right"), ScreenState(), "nav", settle=0)
    gate.execute(press("left"), ScreenState(), "nav", settle=0)
    assert time.monotonic() - t >= 0.14


def test_power_menu_lockdown_only_circle(tmp_path):
    from ps5agent.core.evidence import Evidence
    from ps5agent.core.state import Action, Scenario, ScreenState
    from ps5agent.hw.adapters import FakeRig
    from ps5agent.safety.action_gate import ActionGate
    g = ActionGate(FakeRig(), Evidence(tmp_path), Scenario(id="t", goal="g"))
    pm = ScreenState(screen_id="power_menu")
    assert not g.check(Action(kind="press", name="cross"), pm, "t")[0]
    assert not g.check(Action(kind="press", name="down"), pm, "t")[0]
    assert g.check(Action(kind="press", name="circle"), pm, "t")[0]
    assert not g.check(Action(kind="hold", name="ps", duration=2.0), ScreenState(), "t")[0]
