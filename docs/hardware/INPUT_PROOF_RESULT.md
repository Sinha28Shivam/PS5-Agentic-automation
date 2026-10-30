# Input proof run — result 2026-10-30

## Capture: PASS. Input: FAIL.

```
before  1920x1080  std=37.76  tones=256
after   1920x1080  std=37.75  tones=256

WHOLE-FRAME DELTA = 0.2280          (threshold 0.5)
strongly-changed pixels: 0  (0.0000% of frame)

  game tile row (highlight)    mean=0.2230  max=13  changed>30=0
  clock / top-right            mean=0.0716  max=10  changed>30=0
  widgets lower half           mean=0.2698  max=19  changed>30=0
  store carousel (right)       mean=0.5506  max=19  changed>30=0
```

**The capture half of the rig is now fully proven.** Two clean 1080p frames of
the real PS5 home screen, `std 37.7`, 256 tones. That was the open question an
hour ago and it is settled.

**The input half did not work on this run.** Not one pixel changed by more
than 30 anywhere in the frame. `max=13` across the tile row is sensor noise and
JPEG shimmer, not a moving highlight. Both frames show the clock at `13:46` and
the Mortal Kombat tile selected, unchanged.

## Root cause: the session could never have been authenticated

```
=== 1. DualShock 4 wired to THIS PC ===
  BLOCKER - no DualShock 4 on this PC.

=== 3. No stale gimx.exe holding COM8 ===
  WARNING - gimx.exe running (PID 24884)
```

The GIMX server (PID 24884) answers UDP and `status` happily reports
`OK - GIMX session reachable`, **but there is no DualShock 4 attached to the
PC**. GIMX authenticates PS4/PS5 by pass-through from a genuine DS4, so without
it the session can never arm. Every event is accepted, each one reports `ok`,
and none are delivered.

This is the project's signature failure, reproduced exactly:
**reachable ≠ authenticated ≠ delivering.**

Earlier today the same session logged `found pass-through device
0x054c:0x09cc` and `registered joystick 0 with name "PS4 Controller"`. Neither
line can appear now. The pad left the PC — consistent with it pairing to the
PS5 over Bluetooth, which is the exact risk raised earlier.

## Why `prove_input_reaches_ps5.py` still ran

The script checks `session_is_up()`, which only proves UDP reachability. It
cannot detect a missing auth device, because GIMX does not expose that state
after startup. **Fix applied:** the script now also verifies a DualShock 4 is
present on USB before claiming the session is usable, and says so plainly when
it is not.

## To get a PASS

1. **Unpair the DS4 from the PS5** — hold **PS + SHARE** until the light bar
   double-flashes.
2. **Cable it to the laptop.** Confirm with:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\rig\manual_check.ps1
   ```
   Section 1 must show `PID_09CC` or `PID_05C4`.
3. **Kill the stale session.** PID 24884 was started without the pad and can
   never authenticate:
   ```bash
   python PS5-Automation-Python/gimx-session/gimx_session.py stop
   ```
   If it refuses, it is elevated — close it from an admin Task Manager.
   Do **not** run GIMX as administrator; it takes REALTIME priority and grabs
   input devices, which has frozen a PC during this project's development.
4. **Start a fresh session and TAP PS** when prompted:
   ```bash
   python PS5-Automation-Python/gimx-session/gimx_session.py start
   ```
   Wait for `found pass-through device 0x054c:0x09cc` **and**
   `Press the key/button assigned to PS.` → tap PS on the wired pad.
5. **Re-run the proof:**
   ```bash
   python tools/rig/prove_input_reaches_ps5.py
   ```

## Reading the next result

`compare_proof_frames.py` localises the change, which matters because the PS5
home screen animates by itself (clock, store carousel). A whole-frame delta
alone could be satisfied by a clock tick.

| Signal | Meaning |
|---|---|
| `game tile row ... changed>30` in the thousands | highlight moved — **input arrived** |
| delta ≥ 0.5 but tile row unchanged | PS5's own animation, **not** proof |
| `changed>30 = 0` everywhere (this run) | nothing reached the console |

## Order of operations that matters

The DS4 must be on the PC **before** `gimx_session.py start`. A session started
first will report healthy forever and deliver nothing — which is precisely what
happened here.
