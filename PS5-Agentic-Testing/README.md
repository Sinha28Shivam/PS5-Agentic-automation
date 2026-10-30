# PS5-Agentic-Testing

Fresh agentic layer for **PlayStation 5** console testing. Rebuilt from zero on
2026-10-30; it shares no code, config or artifacts with the previous Xbox
agentic layer.

## Why this was rebuilt rather than ported

The old `Xbox-Agentic-Testing` was correct for an Xbox One and wrong for a PS5
in ways that were not cosmetic:

- **Screen signatures** keyed on `"my games & apps"`, `"buy $"`,
  `"join game pass"` — the executor's safety guard would mis-fire on every PS5
  screen and abort runs.
- **Keyboard layouts** (`xbox_global_search_en`) encoded Xbox's on-screen
  keyboard geometry; PS5's differs in rows, origin and symbol toggle.
- **Routes** were baked Xbox button sequences (`guide → b → y → type...`).
- **Game profiles** targeted Xbox titles (Minecraft Dungeons, Max: The Curse of
  Brotherhood) that are not part of PS5 testing.
- **Lessons / artifacts / test fixtures** were thousands of lines of recorded
  Xbox screen text, which would have taught the planner Xbox behaviour.

Carrying that forward would mean an agent layer that *looks* configured and is
quietly wrong — the exact failure class this project has already paid for.

## What was kept

The **hardware layer** (`PS5-Automation-Python/`) was NOT rebuilt. It is
already PlayStation-native and hardware-verified on this rig:

```
GIMX adapter detected, controller type is: DS4.
Firmware version: 8.0
found pass-through device 0x054c:0x09cc
registered joystick 0 with name "PS4 Controller"
capture: 1920x1080  std=37.7  tones=256
```

Its `controls.yaml` has PlayStation-canonical names (`cross`, `circle`, `ps`,
`options`, `share`, `l1`, `r2`, ...) with the Xbox names retained only as
backward-compatible aliases.

## Status

| Layer | State |
|---|---|
| Hardware: input (DS4 via GIMX/Leonardo) | ✅ verified on hardware |
| Hardware: capture (1080p) | ✅ verified on hardware |
| Agentic: this directory | 🚧 scaffolding, nothing implemented yet |

## Known PS5 constraints (inherited, not solved)

1. **DualShock 4 only.** GIMX cannot emulate a DualSense, so only
   PS4-compatible titles accept this adapter. PS5-native games reject it.
2. **Auth needs a human.** A genuine DS4 must be wired to the PC *before* the
   session starts, and someone must TAP **PS** when GIMX prints
   `Press the key/button assigned to PS.`
3. **HDCP must be off** (Settings → System → HDMI) or capture returns blank
   frames.
4. **One capture consumer.** Close the RECentral GUI and Teams before any run.

## The rule this layer is built around

Accepting an event proves nothing. Only an observed change on the capture card
proves the console reacted. A run with no visual evidence is **BLOCKED**, never
PASS.
