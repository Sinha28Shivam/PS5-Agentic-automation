"""Hardware adapters. The ONLY place that imports PS5-Automation-Python.

`Rig` bundles pad + capture + keyboard + session checks. `FakeRig` replays
recorded frames for offline tests (no hardware, no input sent).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..core.settings import get_settings

_s = get_settings()
for sub in ("test-controller", "gimx-session", "capture"):
    p = str(_s.automation_root / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


class RigLike(Protocol):
    def grab(self) -> np.ndarray | None: ...
    def press(self, name: str, duration: float | None = None) -> bool: ...
    def hold(self, name: str, duration: float) -> bool: ...
    def macro(self, name: str) -> bool: ...
    def type_text(self, text: str) -> bool: ...
    def stick(self, name: str, direction: str, duration: float) -> bool: ...
    def trigger(self, name: str, value: int | None, duration: float | None) -> bool: ...
    def session_up(self) -> bool: ...
    def ds4_present(self) -> bool: ...
    def close(self) -> None: ...


# Control Center icon bar (1080p): x centres of the icons, Home is index 0 and
# Power is the LAST one. Focused icon = white ring. Measured 2026-10-30.
CC_ICONS_X = [400, 505, 624, 735, 846, 960, 1070, 1184, 1294, 1405, 1520]
CC_BAR_Y = (985, 1045)


def cc_focus_scores(frame: np.ndarray) -> list[float]:
    import cv2
    h, w = frame.shape[:2]
    sx, sy = w / 1920.0, h / 1080.0
    g = cv2.cvtColor(frame[int(CC_BAR_Y[0] * sy):int(CC_BAR_Y[1] * sy), :], cv2.COLOR_BGR2GRAY)
    r = int(28 * sx)
    return [float((g[:, int(x * sx) - r:int(x * sx) + r] > 200).mean()) for x in CC_ICONS_X]


def cc_home_focused(frame: np.ndarray) -> bool:
    s = cc_focus_scores(frame)
    return s[0] > 0.4 and s[-1] < 0.3


def home_from_anywhere(rig: Any, max_steps: int = 14) -> bool:
    """PS -> Control Center -> step LEFT until the Home icon is VISIBLY focused -> Cross.

    Never presses Cross unless Home is confirmed focused: the CC remembers the
    last focused icon and Power sits one LEFT of Home (the bar wraps), so a
    blind "ps, down, cross" opened the Power menu during development.
    """
    rig.press("ps"); time.sleep(1.3)
    rig.press("down"); time.sleep(0.6)
    for _ in range(max_steps):
        f = rig.grab()
        if f is not None and cc_home_focused(f):
            rig.press("cross"); time.sleep(2.5)
            return True
        rig.press("left"); time.sleep(0.5)
    rig.press("circle"); time.sleep(0.6)
    return False


# Home game row: caption of the FOCUSED tile is drawn right of it at a fixed
# spot (1080p). PS4/PS5 badge sits at the caption start: PS5 = white badge,
# PS4 = black badge (mean < 35), no badge = dark background (~43) with the
# title starting at the badge position. Measured on 6 frames 2026-10-30.
TILE_CAPTION = {"x": 0.18, "y": 0.215, "width": 0.5, "height": 0.055}
TILE_BADGE_PX = (247, 283, 360, 432)          # y0, y1, x0, x1


def tile_caption(frame: np.ndarray) -> tuple[str, str]:
    """(caption text lower-case, badge 'ps4'|'ps5'|'')."""
    import cv2
    from ..perception.ocr import read_text
    h, w = frame.shape[:2]
    y0, y1, x0, x1 = TILE_BADGE_PX
    g = cv2.cvtColor(frame[int(y0 * h / 1080):int(y1 * h / 1080),
                           int(x0 * w / 1920):int(x1 * w / 1920)], cv2.COLOR_BGR2GRAY)
    m = float(g.mean())
    badge = "ps5" if m > 150 else ("ps4" if m < 32 else "")
    return read_text(frame, TILE_CAPTION), badge


def focus_tile(rig: Any, title: str, badge: str = "", max_moves: int = 16) -> bool:
    """Walk the Home game row until the focused tile caption matches title (+badge).

    Scans right first (recent games are near the start), then left. Verifies by
    the caption - never by counting presses, because the row scrolls.
    """
    from ..perception.signatures import fuzzy_contains
    want = title.lower()

    def here() -> bool:
        f = rig.grab()
        if f is None:
            return False
        cap, b = tile_caption(f)
        return fuzzy_contains(cap.replace(" ", ""), want.replace(" ", ""), 0.8) and \
            (not badge or b == badge)

    def on_row() -> bool:
        f = rig.grab()
        return f is not None and bool(tile_caption(f)[0].strip())

    # Get focus onto the tile row: from widgets go UP, from the top bar go DOWN.
    for _ in range(6):
        if on_row():
            break
        rig.press("up"); time.sleep(0.6)
    else:
        rig.press("down"); time.sleep(0.6)
    for direction in ("left", "right"):
        for _ in range(max_moves):
            if here():
                return True
            rig.press(direction); time.sleep(0.6)
        if here():
            return True
    return False


def ds4_present() -> bool:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "
             "'VID_054C&PID_(05C4|09CC)' } | Select-Object -First 1 -ExpandProperty InstanceId"],
            capture_output=True, text=True, timeout=20).stdout
        return "VID_054C" in out
    except (OSError, subprocess.TimeoutExpired):
        return False


class Rig:
    """Real hardware."""

    def __init__(self, console: str | None = None):
        from capture import ScreenCapture  # type: ignore
        from keyboard import OnScreenKeyboard  # type: ignore
        from test_controller import ConsolePad  # type: ignore

        self.console = console or _s.console_profile
        self.pad = ConsolePad(console=self.console, config_path=_s.controls_config)
        self.cap = ScreenCapture(config_path=_s.controls_config)
        self.cap.open()
        self._kb_cls = OnScreenKeyboard
        self.kb: Any = None

    def grab(self) -> np.ndarray | None:
        # Flush OpenCV's buffered frames so we see the CURRENT screen, not a
        # stale one (measured: without this, a press looked like delta 0.5).
        if self.cap.cap is not None:
            for _ in range(6):
                self.cap.cap.read()
        return self.cap.grab()

    def press(self, name: str, duration: float | None = None) -> bool:
        return self.pad.press(name, duration)

    def hold(self, name: str, duration: float) -> bool:
        return self.pad.hold(name, duration)

    def macro(self, name: str) -> bool:
        if name in ("open_search",):
            self.kb = None                    # keyboard re-opens at initial focus
        if name == "home_from_game":
            return home_from_anywhere(self)
        if name.startswith("focus_tile:"):          # focus_tile:<title>[:ps4|ps5]
            parts = name.split(":")
            return focus_tile(self, parts[1].replace("_", " "),
                              parts[2] if len(parts) > 2 else "")
        return self.pad.run_macro(name)

    def type_text(self, text: str) -> bool:
        if self.kb is None:
            self.kb = self._kb_cls(self.pad)
        return self.kb.type_text(text)

    def reset_keyboard(self) -> None:
        self.kb = None

    def stick(self, name: str, direction: str, duration: float) -> bool:
        return self.pad.stick(name, direction, duration=duration)

    def trigger(self, name: str, value: int | None, duration: float | None) -> bool:
        return self.pad.trigger(name, value, duration=duration) if duration else \
            self.pad.trigger(name, value)

    def session_up(self) -> bool:
        from gimx_session import session_is_up  # type: ignore
        return bool(session_is_up(_s.controls_config, self.console, quiet=True))

    def ds4_present(self) -> bool:
        return ds4_present()

    def close(self) -> None:
        try:
            self.cap.close()
        except Exception:  # noqa: BLE001
            pass


class FakeRig:
    """Offline rig: serves frames from a directory in order; records actions."""

    def __init__(self, frames_dir: Path | str | None = None, frames: list[np.ndarray] | None = None):
        import cv2
        self.frames: list[np.ndarray] = list(frames or [])
        if frames_dir:
            for p in sorted(Path(frames_dir).glob("*.*g")):
                img = cv2.imread(str(p))
                if img is not None:
                    self.frames.append(img)
        if not self.frames:
            self.frames = [np.full((1080, 1920, 3), 40, np.uint8)]
        self.i = 0
        self.actions: list[str] = []

    def _advance(self) -> None:
        self.i = min(self.i + 1, len(self.frames) - 1)

    def grab(self) -> np.ndarray | None:
        return self.frames[self.i].copy()

    def press(self, name: str, duration: float | None = None) -> bool:
        self.actions.append(f"press:{name}"); self._advance(); return True

    def hold(self, name: str, duration: float) -> bool:
        self.actions.append(f"hold:{name}"); self._advance(); return True

    def macro(self, name: str) -> bool:
        self.actions.append(f"macro:{name}"); self._advance(); return True

    def type_text(self, text: str) -> bool:
        self.actions.append(f"type:{text}"); self._advance(); return True

    def stick(self, name: str, direction: str, duration: float) -> bool:
        self.actions.append(f"stick:{name}:{direction}"); self._advance(); return True

    def trigger(self, name: str, value: int | None, duration: float | None) -> bool:
        self.actions.append(f"trigger:{name}"); self._advance(); return True

    def reset_keyboard(self) -> None:
        pass

    def session_up(self) -> bool:
        return True

    def ds4_present(self) -> bool:
        return True

    def close(self) -> None:
        pass


def perform(rig: Any, action: Any) -> bool:
    """Execute a core.state.Action on a rig. Single dispatch point."""
    k = action.kind
    ok = True
    for i in range(max(1, action.times if k in ("press", "hold", "macro") else 1)):
        if k == "press":
            ok = rig.press(action.name, action.duration) and ok
        elif k == "hold":
            ok = rig.hold(action.name, action.duration or 1.0) and ok
        elif k == "macro":
            ok = rig.macro(action.name) and ok
        elif k == "type":
            ok = rig.type_text(action.text or "") and ok
        elif k == "stick":
            ok = rig.stick(action.name or "left_stick", action.direction or "right",
                           action.duration or 0.5) and ok
        elif k == "trigger":
            ok = rig.trigger(action.name, action.value, action.duration) and ok
        elif k == "wait":
            time.sleep(action.duration or 1.0)
        if action.interval and i < action.times - 1:
            time.sleep(action.interval)
    return ok
