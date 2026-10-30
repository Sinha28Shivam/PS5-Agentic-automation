"""
ps5_profile_check.py - offline guard for the PS5 (DualShock 4) migration.

Validates controls.yaml and the console-profile plumbing WITHOUT any hardware,
GIMX install or serial port. Run after editing console profiles or the button
map:

    python tools/rig/ps5_profile_check.py

It checks the things that broke silently during the Xbox build:
  * every Xbox-era control name still resolves (aliases preserved)
  * the default profile is the PlayStation one and emulates DS4
  * PS5/PS4 profiles do NOT claim an Xbox-style auth gesture
  * a profile with config_file: null is refused rather than started
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = REPO_ROOT / "PS5-Automation-Python"
sys.path.insert(0, str(AUTOMATION / "test-controller"))
sys.path.insert(0, str(AUTOMATION / "gimx-session"))

from test_controller import ControlConfig  # noqa: E402

import gimx_session  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))
        failures.append(label)


cfg = ControlConfig()

print("\n-- 1. legacy Xbox names still resolve (no scenario may break) --")
# Xbox name -> the GIMX wire name it must still produce.
legacy = {
    "a": "cross", "b": "circle", "x": "square", "y": "triangle",
    "guide": "PS", "xbox": "PS", "home": "PS", "dashboard": "PS",
    "menu": "start", "start": "start", "pause": "start",
    "view": "select", "select": "select", "back": "select",
    "lb": "l1", "rb": "r1", "lt": "l2", "rt": "r2",
    "ls": "l3", "rs": "r3",
    "confirm": "cross", "cancel": "circle",
}
for name, expected in legacy.items():
    try:
        got = cfg.gimx_name(name)
    except KeyError as exc:
        check(f"{name!r} resolves", False, str(exc)[:60])
        continue
    check(f"{name!r} -> {expected!r}", got == expected, f"got {got!r}")

print("\n-- 2. new PlayStation names resolve --")
ps_names = {
    "cross": "cross", "circle": "circle", "square": "square",
    "triangle": "triangle", "ps": "PS", "options": "start",
    "share": "select", "create": "select",
    "l1": "l1", "r1": "r1", "l2": "l2", "r2": "r2",
    "l3": "l3", "r3": "r3",
}
for name, expected in ps_names.items():
    try:
        got = cfg.gimx_name(name)
    except KeyError as exc:
        check(f"{name!r} resolves", False, str(exc)[:60])
        continue
    check(f"{name!r} -> {expected!r}", got == expected, f"got {got!r}")

print("\n-- 3. default console profile is PlayStation/DS4 --")
default = cfg.console_profile()
check("default emulates DS4", default.get("gimx_type") == "DS4",
      f"got {default.get('gimx_type')!r}")
check("default uses EMUPS4 firmware", default.get("firmware") == "EMUPS4",
      f"got {default.get('firmware')!r}")
check("default authenticates with a DualShock 4",
      default.get("auth_device") == "dualshock4",
      f"got {default.get('auth_device')!r}")

print("\n-- 4. auth gesture is per-family and correct --")
# CORRECTED 2026-10-30. An earlier revision asserted PlayStation needed NO
# gesture. Hardware disproved it: GIMX prints "Press the key/button assigned
# to PS." for a DS4 session too. It is a TAP of PS, not a 2s hold of Guide,
# but it is still a required human action.
for name in ("ps5", "ps4"):
    prof = cfg.consoles.get(name, {})
    check(f"{name}: auth_gesture is tap_ps",
          prof.get("auth_gesture") == "tap_ps",
          f"got {prof.get('auth_gesture')!r}")
check("no Xbox console profiles remain",
      not any(n.startswith("xbox") for n in cfg.consoles),
      f"got {sorted(cfg.consoles)!r}")

print("\n-- 4b. PlayStation profiles have a real GIMX config --")
for name in ("ps5", "ps4"):
    prof = cfg.consoles.get(name, {})
    cfg_file = prof.get("config_file")
    check(f"{name}: config_file is set", bool(cfg_file), f"got {cfg_file!r}")

print("\n-- 5. the removed Xbox auth macro is really gone --")
check("special_actions has no guide_auth", "guide_auth" not in cfg.special)
check("special_actions gained control_center", "control_center" in cfg.special)

print("\n-- 6. ps5 session builds, and the guard still catches a null config --")
# ps5 now HAS a config (Dualshock4.xml), so it must construct cleanly...
try:
    sess = gimx_session.GimxSession(console="ps5")
except Exception as exc:
    check("GimxSession(ps5) constructs", False, f"{type(exc).__name__}: {exc}")
else:
    check("GimxSession(ps5) constructs", True)
    check("ps5 session uses --type DS4", sess.ctype == "DS4", f"got {sess.ctype!r}")
    check("ps5 session uses Dualshock4.xml",
          sess.gimx_config == "Dualshock4.xml", f"got {sess.gimx_config!r}")
    cmd = sess.build_command()
    check("--config present in command line", "--config" in cmd, " ".join(cmd))
    # GIMX docs: "--port finishes the current controller options", so anything
    # after it lands on a non-existent controller #2.
    check("--port is LAST argument", cmd[-2] == "--port", " ".join(cmd[-4:]))

# ...while a profile with no config must STILL be refused. This is the
# project's most expensive failure mode: GIMX with no --config starts, reports
# the adapter, accepts events and forwards nothing.
try:
    gimx_session.GimxSession(console="ps3")
except ValueError as exc:
    check("GimxSession(ps3) raises while its config_file is null",
          "config_file" in str(exc), str(exc)[:70])
else:
    check("GimxSession(ps3) raises while its config_file is null", False,
          "constructed a session that cannot deliver input")

print("\n-- 7. unknown profile names fail loudly (no XOnePad fallback) --")
try:
    gimx_session.GimxSession(console="ps6")
except KeyError as exc:
    check("unknown console raises KeyError", True)
except ValueError as exc:
    check("unknown console raises KeyError", False, f"ValueError: {exc}")
else:
    check("unknown console raises KeyError", False, "no error raised")

print()
if failures:
    print(f"RESULT: {len(failures)} check(s) FAILED")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("RESULT: all checks passed")
