# PS5 Agentic Automation

Automated testing of a **PlayStation 5** through a GIMX adapter (Arduino
Leonardo flashed with `EMUPS4`, emulating a DualShock 4) and an HDMI capture
card. A genuine **DualShock 4 wired to the PC** provides authentication.

```
PC ──USB──> FTDI ──UART──> Leonardo (EMUPS4) ──USB──> PS5
 │                                                    │
 └── DS4 (auth pass-through, tap PS)                  │
 └── capture card <──────────── HDMI ─────────────────┘
```

## Layout

| Path | What |
|---|---|
| [`PS5-Automation-Python/`](PS5-Automation-Python/) | Hardware layer (verified): flasher, GIMX session, controller input, capture, diagnostics, tests, docs. See its [README](PS5-Automation-Python/README.md). |
| [`PS5-Agentic-Testing/`](PS5-Agentic-Testing/) | Agentic layer (scaffolding only). See its [README](PS5-Agentic-Testing/README.md) and [REBUILD_NOTES](PS5-Agentic-Testing/REBUILD_NOTES.md). |

## Quick start

```powershell
pip install -r PS5-Automation-Python\requirements.txt
python PS5-Agentic-Testing\validate_config.py          # offline config checks
cd PS5-Automation-Python
python tests\ps5_profile_check.py                       # offline profile checks
python gimx-session\gimx_session.py start               # then TAP PS on the DS4
python tests\prove_input_reaches_ps5.py                 # before -> input -> after proof
```

## PS5 constraints

1. **DualShock 4 only** — GIMX cannot emulate a DualSense, so only
   PS4-compatible titles accept input.
2. **Auth needs a human** — tap **PS** on the wired DS4 when GIMX prompts.
3. **HDCP off** (Settings → System → HDMI) or capture returns blank frames.
4. **One capture consumer** — close RECentral/Teams before a run.
5. **Never run GIMX elevated** — it can freeze the PC.
