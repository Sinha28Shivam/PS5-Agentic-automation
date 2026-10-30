"""
validate_config.py - sanity-check the scaffolded PS5 config. No hardware needed.

    python PS5-Agentic-Testing/validate_config.py

Checks the config is parseable, points at the PS5 hardware layer, and carries
no leftover Xbox assumptions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))
        failures.append(label)


print("\n-- settings.yaml --")
settings = yaml.safe_load((HERE / "config" / "settings.yaml").read_text(encoding="utf-8"))
check("parses", isinstance(settings, dict))
check("console is ps5", settings["meta"].get("console") == "ps5")
check("automation_root -> PS5-Automation-Python",
      "PS5-Automation-Python" in settings["paths"]["automation_root"])
check("controls_config -> PS5-Automation-Python",
      "PS5-Automation-Python" in settings["paths"]["controls_config"])
check("emulates DS4", settings["console"]["emulated_controller"] == "DS4")
check("PS4-titles-only flag set", settings["console"]["ps4_titles_only"] is True)
check("auth gesture is tap_ps", settings["console"]["auth"]["gesture"] == "tap_ps")
check("auth needs a human", settings["console"]["auth"]["requires_human"] is True)
check("HDCP-off requirement recorded",
      settings["console"]["requires_hdcp_disabled"] is True)
check("visual evidence required",
      settings["runtime"]["require_visual_evidence"] is True)
# The capture card needs ~1.05 s to lock on; a shorter wait reports a false
# "no signal" on a healthy card. Verified the hard way on 2026-10-30.
check("capture sync timeout >= 1.05s",
      float(settings["verification"]["capture_sync_timeout"]) >= 1.05,
      str(settings["verification"].get("capture_sync_timeout")))

print("\n-- no Xbox leftovers in settings --")
blob = yaml.dump(settings).lower()
for bad in ("xbox", "xonepad", "emuxone", "game pass", "minecraft", "dungeons"):
    check(f"no {bad!r}", bad not in blob)

print("\n-- screen_signatures.yaml --")
sigs = yaml.safe_load((HERE / "config" / "screen_signatures.yaml").read_text(encoding="utf-8"))
check("parses", isinstance(sigs, dict))
check("console is ps5", sigs["meta"].get("console") == "ps5")
check("marked UNVERIFIED (honest default)", sigs["meta"].get("verified") is False)
check("home signatures present", len(sigs.get("home") or []) > 0)
check("in_game is empty (must be filled per title)",
      (sigs.get("in_game") or []) == [])
sigblob = yaml.dump(sigs).lower()
for bad in ("my games & apps", "join game pass", "buy $", "sponsored"):
    check(f"no Xbox signature {bad!r}", bad not in sigblob)

print("\n-- hardware layer reachable --")
hw = REPO / "PS5-Automation-Python"
check("PS5-Automation-Python exists", hw.is_dir())
check("legacy Xbox-Automation-Python is gone",
      not (REPO / "Xbox-Automation-Python").exists())

print()
if failures:
    print(f"RESULT: {len(failures)} check(s) FAILED")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: all checks passed")
