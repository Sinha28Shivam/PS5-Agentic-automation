"""
keyboard.py - type text on the PS5 on-screen keyboard by grid navigation.

Geometry comes from controls.yaml `text_entry.keyboard_layouts.<variant>`;
nothing about the keyboard is hardcoded here.

    from test_controller import ConsolePad
    from keyboard import OnScreenKeyboard

    kb = OnScreenKeyboard(ConsolePad())
    print(kb.plan("ps5 pro"))          # dry: list of presses
    kb.type_text("ps5 pro")            # keyboard must already be open,
                                       # focus on its initial key

CLI (keyboard already open on the PS5):
    python keyboard.py plan "ps5 pro"
    python keyboard.py type "ps5 pro"

Only characters on the abc / abc_shift pages are supported. Space and
backspace use their controller shortcuts. Case is ignored: PS5 search is
case-insensitive and the first letter is auto-capitalised anyway.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from test_controller import DEFAULT_CONFIG_PATH, ConsolePad, ControlConfig


class OnScreenKeyboard:
    def __init__(self, pad: ConsolePad | None = None,
                 variant: str | None = None,
                 config: ControlConfig | None = None):
        self.pad = pad
        cfg = config or (pad.cfg if pad else ControlConfig(DEFAULT_CONFIG_PATH))
        te: dict[str, Any] = cfg.data.get("text_entry", {})
        self.defaults: dict[str, Any] = te.get("defaults", {})
        variant = variant or self.defaults.get("keyboard_variant")
        layouts = te.get("keyboard_layouts", {})
        if variant not in layouts:
            raise KeyError(f"Unknown keyboard layout {variant!r}. "
                           f"Known: {', '.join(layouts)}")
        self.variant = variant
        self.layout: dict[str, Any] = layouts[variant]
        self.shortcuts: dict[str, str] = self.layout.get("shortcuts", {})
        self.wrap_h = bool(self.layout.get("wrap_horizontal", False))
        self.rows: list[list[str]] = self.layout["pages"]["abc"]["rows"]
        self.cols = max(len(r) for r in self.rows)

        self.index: dict[str, tuple[int, int]] = {}
        for page in ("abc", "abc_shift"):
            for r, row in enumerate(self.layout["pages"].get(page, {}).get("rows", [])):
                for c, ch in enumerate(row):
                    if ch:
                        self.index.setdefault(ch.lower(), (r, c))
        self.pos = self.index[str(self.layout["initial_focus"]).lower()]

    def _hmoves(self, c0: int, c1: int) -> tuple[str, int]:
        right = (c1 - c0) % self.cols if self.wrap_h else max(c1 - c0, 0)
        left = (c0 - c1) % self.cols if self.wrap_h else max(c0 - c1, 0)
        if not self.wrap_h:
            return ("right", c1 - c0) if c1 >= c0 else ("left", c0 - c1)
        return ("right", right) if right <= left else ("left", left)

    def plan(self, text: str) -> list[str]:
        """Return the button presses that would type `text`."""
        presses: list[str] = []
        r, c = self.pos
        for ch in text:
            if ch == " ":
                presses.append(self.shortcuts["space"])
                continue
            key = ch.lower()
            if key not in self.index:
                raise ValueError(f"{ch!r} is not on the {self.variant} abc page")
            tr, tc = self.index[key]
            presses += ["down" if tr > r else "up"] * abs(tr - r)
            direction, n = self._hmoves(c, tc)
            presses += [direction] * n
            presses.append(self.shortcuts.get("type_focused", "cross"))
            r, c = tr, tc
        return presses

    def type_text(self, text: str) -> bool:
        if self.pad is None:
            raise RuntimeError("no ConsolePad - use plan() for a dry run")
        move = float(self.defaults.get("move_interval", 0.3))
        key_pause = float(self.defaults.get("key_pause", 0.4))
        ok = True
        for b in self.plan(text):
            ok = self.pad.press(b) and ok
            time.sleep(key_pause if b in self.shortcuts.values() else move)
        r, c = self.pos
        for ch in text:
            if ch != " ":
                r, c = self.index[ch.lower()]
        self.pos = (r, c)
        return ok

    def backspace(self, n: int = 1) -> None:
        for _ in range(n):
            self.pad.press(self.shortcuts["backspace"])
            time.sleep(float(self.defaults.get("key_pause", 0.4)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Type on the PS5 on-screen keyboard")
    ap.add_argument("action", choices=["plan", "type"])
    ap.add_argument("text")
    ap.add_argument("--console", default=None)
    ap.add_argument("--variant", default=None)
    a = ap.parse_args()
    if a.action == "plan":
        kb = OnScreenKeyboard(variant=a.variant)
        print(" ".join(kb.plan(a.text)))
        return 0
    kb = OnScreenKeyboard(ConsolePad(console=a.console), variant=a.variant)
    return 0 if kb.type_text(a.text) else 1


if __name__ == "__main__":
    sys.exit(main())
