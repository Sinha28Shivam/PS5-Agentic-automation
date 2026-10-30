# Manual signal test — verify by eye that input reaches the PS5

Watching the TV is the **strongest** evidence available. Everything the
automated tooling does is an attempt to approximate what your eyes do directly.
Doing this first is the right call.

Run the gate first; it checks the four preconditions:

```powershell
powershell -ExecutionPolicy Bypass -File tools\rig\manual_check.ps1
```

---

## Two blockers must be cleared first

### 1. The DualShock 4 is NOT on the PC

```
=== 6. Sony controller (VID_054C - DS4 auth pad) ===
  No Sony controller present on this PC.
```

GIMX authenticates by **pass-through from a genuine DS4 wired to the PC**.
Without it the session can never arm, no matter how many times you tap PS.

If the pad paired to the PS5 over Bluetooth it has left the PC:

1. Hold **PS + SHARE** together until the light bar double-flashes → unpaired.
2. Plug it into the **laptop** with a **data** USB cable.
3. Re-run `manual_check.ps1`; section 1 must show `PID_09CC` or `PID_05C4`.

> The PS5 and the PC are competing for this one controller. For the whole of a
> test session the DS4 belongs to the **PC**. The console gets its input from
> the Leonardo, not from this pad.

### 2. A stale, ELEVATED gimx.exe is holding COM8

```
Stopping gimx.exe (pid 13512) ...
  Could NOT stop pid [13512]. It is probably running elevated.
```

Two separate problems here:

**(a) It is stale.** It was started before the DS4 was connected, so it never
authenticated — yet `gimx_session.py status` still cheerfully reports
`OK - GIMX session reachable`. This is the project's signature failure mode:
reachable ≠ authenticated ≠ delivering.

**(b) It is elevated, which is dangerous.** Per `gimx_session.py`'s own header:
an elevated GIMX claims REALTIME CPU priority and grabs input devices — during
development this **froze an entire PC** (stuck mouse, nothing clickable). Note
the earlier probe also logged `Highest priority class can't be used due to
missing elevation`, i.e. a non-elevated GIMX is *deliberately* safer.

**Do not run GIMX as administrator.** Close that process from its own window,
or from an **admin** Task Manager. Then start sessions normally — the wrapper
passes `--nograb` and `--timeout` and pins priority to Normal.

---

## The procedure

```powershell
# 0. clear both blockers, then confirm
powershell -ExecutionPolicy Bypass -File tools\rig\manual_check.ps1
```

1. **Put the PS5 on a screen that can visibly react.**
   The home row of game tiles, or Settings. It must have a **moving
   highlight**. A static splash screen cannot show a d-pad press, and you
   would wrongly conclude the signal failed.

2. **Start the session** (leave this terminal open):
   ```bash
   python PS5-Automation-Python/gimx-session/gimx_session.py start
   ```
   Expect:
   ```
   GIMX adapter detected, controller type is: DS4.
   Firmware version: 8.0
   found pass-through device 0x054c:0x09cc
   registered joystick 0 with name "PS4 Controller"
   Press the key/button assigned to PS.
   ```

3. **TAP PS on the wired DualShock 4.** Not a hold — a tap. This arms the
   session. Skipping it is the single most common cause of "everything says ok
   and nothing moves".

4. **Second terminal — send a deliberately visible pattern:**
   ```bash
   python PS5-Automation-Python/test-controller/test_controller.py --console ps5 macro nav_test
   ```
   `nav_test` is right×2 → left×2 → down → up with 0.8 s gaps, chosen to be
   unmistakable on a menu.

5. **Watch the TV, not the terminal.**

---

## Reading the result

| What you see | Meaning |
|---|---|
| **Highlight moves right, right, left, left, down, up** | Signal confirmed end to end. The chain works. |
| Terminal says `ok`, TV does nothing | GIMX accepted and delivered nothing. Cause order: (1) PS not tapped, (2) DS4 not on the PC, (3) the stale elevated session is the one holding COM8, (4) static screen. |
| `can't get controller type from remote gimx` | No session reachable — step 2 did not stay running. |
| TV shows nothing at all, screen black | Not an input problem. HDMI/HDCP — unrelated to this test if you are watching the TV directly. |

Single presses are also fine for a quick check:

```bash
python PS5-Automation-Python/test-controller/test_controller.py --console ps5 press right
python PS5-Automation-Python/test-controller/test_controller.py --console ps5 press down
```

> **Do not press `cross` / `a` blindly.** It confirms whatever is highlighted
> and may launch a game or change a setting. Use d-pad directions to test —
> they are reversible.

---

## After it passes

Only then is the capture card worth fixing (close the **RECentral GUI**, turn
**HDCP off**), so the automated equivalent can run:

```bash
python tools/rig/prove_input_reaches_ps5.py
```

Manual success proves the hardware path. The scripted test proves the
*framework* can observe it — which is what the agents need.
