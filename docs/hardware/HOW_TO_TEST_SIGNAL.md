# How to test whether input is actually reaching the PS5

## First: the DualShock 4 must stay WIRED to the PC

> "it will connect wirelessly then how to test it is sending the signal or not"

**Do not let the DS4 connect wirelessly.** If it pairs to the PS5 over
Bluetooth it leaves the PC, and GIMX loses the device it needs for
authentication pass-through. That is not a testing inconvenience - the rig
stops working entirely.

Observed on this rig at 09:14 today: `rig_probe.ps1` reported

```
=== 6. Sony controller (VID_054C - DS4 auth pad) ===
  No Sony controller present on this PC.
```

…where minutes earlier GIMX had logged `found pass-through device
0x054c:0x09cc`. The pad had gone. A running GIMX server (PID 8008) was still
holding COM8 and still answering UDP as "reachable" - a textbook example of a
session that looks perfectly healthy and can deliver nothing.

### The two radios, and which one must stay off

| Link | Who talks | Must it be wireless? |
|---|---|---|
| DS4 -> **PC** (USB cable) | auth pass-through to GIMX | **NO - keep it wired** |
| Leonardo -> **PS5** (USB cable) | the emulated DS4 the console sees | NO - wired |
| Your hands -> DS4 | the one-time PS tap to arm the session | n/a |

Nothing in this rig needs Bluetooth. If the DS4 shows up on the PS5's user
list, it has paired to the console - hold **PS + Share** until the light bar
flashes to unpair it, then reconnect it to the laptop by cable.

Keep the DS4 wired and watch for it vanishing:

```powershell
powershell -ExecutionPolicy Bypass -File tools\rig\rig_probe.ps1
```

Section 6 must show `PID_09CC` (DS4 v2) or `PID_05C4` (DS4 v1).

---

## The test itself: a pixel change, nothing less

`gimx accepted the event` is **not** a signal test. An unauthenticated session
accepts every event, prints `ok`, and delivers nothing - the exact failure that
cost this project hours (`docs/07-lessons-learned.md`).

The only honest test is **before / input / after** on the capture card:

```bash
python tools/rig/prove_input_reaches_ps5.py
```

It will:

1. confirm a GIMX session is reachable,
2. confirm the capture card opens (and **stop** if it cannot),
3. grab a BEFORE frame and reject it if blank,
4. press `right` three times via the real `ConsolePad`,
5. grab an AFTER frame,
6. print the mean pixel delta and a PASS/FAIL verdict,
7. save both frames to `artifacts/rig/input-proof/`.

A delta above the threshold is proof the whole chain works:

```
python -> gimx client -> UDP -> gimx server -> COM8
       -> FTDI -> Leonardo (EMUPS4/DS4) -> PS5
```

### What a FAIL cannot tell you

A no-change result has two causes the test cannot separate:
(a) input never arrived, or (b) it arrived but the screen had no visible
reaction. That is why it presses a **navigation** button and why you should
run it **on a menu with a visible highlight** - never on a static screen.

---

## Current blockers (as of this run)

| # | Blocker | Fix |
|---|---|---|
| 1 | **RECentral 4 is running** and holding the capture card. Only ONE app can open a capture device. | Close RECentral 4 completely (check the tray) |
| 2 | **The DS4 is no longer on the PC** | Re-connect it by USB cable; do not pair it to the PS5 |
| 3 | **HDCP** on the PS5 system UI blanks the capture | Settings > System > HDMI > Enable HDCP -> OFF |
| 4 | A stale `gimx.exe` (PID 8008) is holding COM8 from an unverified session | `python PS5-Automation-Python/gimx-session/gimx_session.py stop` |

Note index 1 probed as `1280x720, std 1.58` - that is the **HP HD Camera**,
not the console. `capture.py` resolves the card by NAME for exactly this
reason; do not "fix" a blank capture by switching to index 1 or you will be
testing against your own webcam, as already happened once (see the
`controls.yaml` capture notes, 2026-08-14).

---

## Correct order of operations

```bash
# 0. close RECentral 4; wire the DS4 to the laptop; HDCP off; PS5 on a menu

# 1. clear any stale session
python PS5-Automation-Python/gimx-session/gimx_session.py stop

# 2. confirm the rig
powershell -ExecutionPolicy Bypass -File tools\rig\rig_probe.ps1
cd PS5-Automation-Python && python capture\capture.py preflight

# 3. start the session, then TAP PS on the DualShock 4 when prompted
python PS5-Automation-Python/gimx-session/gimx_session.py start

# 4. prove it (second terminal)
python tools/rig/prove_input_reaches_ps5.py
```
