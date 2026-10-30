# PS5-Automation-Python — hardware layer

Everything needed to drive a PS5 from the PC: flash the adapter, start an
authenticated GIMX session, send controller input, and capture the screen.
Run all commands from this folder.

| Path | What |
|---|---|
| `config/controls.yaml` | Single source of truth: console profiles, buttons, timing, capture, macros |
| `flash-leonardo/flash_leonardo.ps1` | Flash EMUPS4 onto the Leonardo (tap RESET when prompted) |
| `flash-leonardo/adapter_probe.ps1` | Confirm the adapter reports `controller type is: DS4` |
| `gimx-session/gimx_session.py` | Start / status / stop the GIMX session (`start`, then **tap PS** on the wired DS4) |
| `test-controller/test_controller.py` | Send buttons, sticks, triggers, macros |
| `capture/capture.py` | Capture card: `preflight`, `grab`, `watch` |
| `console-connector/console_connector.py` | Low-level serial link probe (FTDI ↔ Leonardo) |
| `diagnostics/rig_probe.ps1` | Read-only rig snapshot: GIMX install, COM ports, FTDI, DS4, COM8 lock |
| `diagnostics/free_capture.ps1` | List / close apps holding the capture card (`-Close`) |
| `tests/` | Offline self-tests + `prove_input_reaches_ps5.py` (real before→input→after proof) |
| `docs/` | Flashing, capture and signal-test notes; `reference/` holds a verified 1080p PS5 frame |
| `artifacts/` | Output from proof runs (gitignored) |

## Normal run

```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File diagnostics\rig_probe.ps1
python capture\capture.py preflight
python gimx-session\gimx_session.py start        # then TAP PS on the DS4
# second terminal:
python tests\prove_input_reaches_ps5.py
```

## Offline checks (no hardware)

```powershell
python tests\ps5_profile_check.py
python tests\gimx_session_selftest.py
python tests\test_controller_selftest.py
```

## Flashing

See [docs/FLASH_NOTES.md](docs/FLASH_NOTES.md).
