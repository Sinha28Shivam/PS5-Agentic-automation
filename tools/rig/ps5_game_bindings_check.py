"""
ps5_game_bindings_check.py - every game-profile binding still resolves.

The game-control YAMLs (dungeons_controls.yaml, minecraft_controls.yaml) are
verbatim transcriptions of each game's own in-game Controls screen, so they use
the names printed there ("a", "x", "rt", "lb"). After controls.yaml became
PlayStation-native those became ALIASES rather than canonical names.

This asserts each one still maps to a real GIMX wire name, so a future rename
cannot silently strand a game profile.

    python tools/rig/ps5_game_bindings_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

AUTOMATION = REPO_ROOT / "PS5-Automation-Python"
AGENTIC = REPO_ROOT / "PS5-Agentic-Testing"
sys.path.insert(0, str(AUTOMATION / "test-controller"))

from test_controller import ControlConfig  # noqa: E402

cfg = ControlConfig()
failures: list[str] = []

# Game control maps are verbatim transcriptions of each game's own in-game
# Controls screen. The Xbox-era ones (Minecraft Dungeons, Minecraft Bedrock)
# were deleted with the Xbox agent layer, so there are none yet: this file
# discovers whatever *_controls.yaml the PS5 layer defines rather than naming
# titles that no longer exist.
GAME_CONFIGS = {
    p.stem.replace("_controls", ""): p
    for p in sorted((AGENTIC / "config").glob("*_controls.yaml"))
} if (AGENTIC / "config").is_dir() else {}

if not GAME_CONFIGS:
    # Reporting "every binding resolves" while checking zero bindings is the
    # dishonest-green this project exists to avoid. Say so and exit neutral.
    print("\n  No game control maps found under "
          f"{AGENTIC / 'config'}")
    print("  Nothing to check. This is EXPECTED right after the Xbox wipe:")
    print("  add <game>_controls.yaml per title, transcribed from the game's")
    print("  own in-game Controls screen, then re-run.")
    raise SystemExit(0)

for game, path in GAME_CONFIGS.items():
    print(f"\n-- {game} ({path.name}) --")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    for action, entry in (data.get("bindings") or {}).items():
        name = entry.get("button")
        try:
            wire = cfg.gimx_name(name)
        except KeyError:
            print(f"  FAIL  {action:22s} '{name}' resolves to nothing")
            failures.append(f"{game}.{action}")
            continue
        print(f"  PASS  {action:22s} {name!r:10s} -> {wire!r}")

    # Sticks are referenced by canonical stick name, not via the alias map.
    for role, stick in (data.get("sticks") or {}).items():
        if stick in cfg.sticks:
            print(f"  PASS  {role:22s} {stick!r:10s} -> stick")
        else:
            print(f"  FAIL  {role:22s} '{stick}' is not a known stick")
            failures.append(f"{game}.{role}")

print()
if failures:
    print(f"RESULT: {len(failures)} binding(s) FAILED to resolve")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("RESULT: every game binding resolves")
