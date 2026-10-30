# tools/rig — PS5 rig tooling

Hardware probes and diagnostics for the PS5 / DualShock 4 rig. Not part of the
product; these are the scripts used to bring the hardware up and prove it works.
All paths below are relative to the repo root, e.g.
`powershell -ExecutionPolicy Bypass -File tools\rig\rig_probe.ps1`.

- Scripts write their output frames to `artifacts/rig/` (gitignored).
- Findings / write-ups live in [`docs/hardware/`](../../docs/hardware/).
- The verified 1080p PS5 home frame is
  [`docs/hardware/reference/ps5-home-1080p.png`](../../docs/hardware/reference/ps5-home-1080p.png).

## Bring-up and flashing

| Script | Purpose |
|---|---|
| `rig_probe.ps1` | Full rig snapshot: GIMX, COM ports, FTDI, Arduino, DS4, COM8 lock |
| `arduino_state.ps1` | Leonardo in BOOTLOADER / sketch / GIMX-gamepad state? |
| `driver_check.ps1` | Driver error codes and phantom (`CM_PROB_PHANTOM`) nodes |
| `port_watch.ps1` | Live COM port appear/disappear timeline |
| **`flash_pounce.ps1`** | **Use this to flash EMUPS4.** Inline avrdude; never opens the port |
| `flash_retry.ps1` / `flash_ps4_guided.ps1` | Retry loop / guided variants |
| `adapter_probe.ps1` | Asks the adapter its firmware — proves `DS4` vs `XOnePad` |
| `find_gimx_configs.ps1` | Locates GIMX `.xml` configs (in `%APPDATA%\gimx\config`) |

## Capture

| Script | Purpose |
|---|---|
| `capture_diagnose.ps1` | Hardware, drivers, holders, camera privacy policy |
| `card_health.ps1` | USB controller generation vs offered formats |
| `check_input_resolution.ps1` | What resolution is actually arriving |
| `deep_capture_test.ps1` | Sustained 3 s capture per mode — the decisive test |
| `grab_by_name.ps1` | One frame **by device name**, never by index |
| `watch_signal.ps1` | Live polling while changing PS5 settings |
| `free_capture.ps1` | Lists/closes apps holding the card (`-Close`) |
| `reset_capture_card.ps1` | Power-cycle the card (admin) or physical steps |
| `capture_warmup_test.py` | Reproduces the ~1.05 s HDMI lock-on behaviour |

## Session, input and proof

| Script | Purpose |
|---|---|
| `manual_check.ps1` | Four-point gate before a manual signal test |
| `gimx_session_selftest.py` | Command assembly + safety flags, no hardware |
| `test_controller_selftest.py` | Alias resolution and dry-run dispatch |
| `ps5_profile_check.py` | 26 offline checks on the PS5 console profiles |
| `ps5_game_bindings_check.py` | Game bindings resolve to real GIMX names |
| `prove_input_reaches_ps5.py` | **The honest input test**: before → input → after |
| `compare_proof_frames.py` | Re-measures saved frames and localises the change |

## Findings — read before re-debugging anything (in `docs/hardware/`)

| Document | Covers |
|---|---|
| `FLASH_NOTES.md` | Why EMUPS4 flashing failed; the ghost-COM-port trap |
| `CAPTURE_DIAGNOSIS.md` | Why the card looked dead and was not |
| `FIX_CAPTURE.md` | HDMI IN vs OUT, forcing 1080p, HDCP |
| `HOW_TO_TEST_SIGNAL.md` | Why the DS4 must stay **wired to the PC** |
| `MANUAL_SIGNAL_TEST.md` | Manual eyeball procedure |
| `INPUT_PROOF_RESULT.md` | The last proof run and why it failed |

## Two lessons worth keeping

1. **Capture probes must allow ≥ 1.05 s.** The card returns ~2 flat frames
   while locking onto HDMI; a shorter probe reports "no signal" on a perfectly
   healthy card. That cost a full misdiagnosis.
2. **Never resolve the capture device by index.** Index 1 is the laptop
   webcam. `capture.py` matches by name on purpose.
