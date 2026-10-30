# PS5 / DualShock 4 rig — flash + adapter verification

## Adapter verified 2026-10-30

`tools\rig\adapter_probe.ps1` produced:

```
GIMX adapter detected, controller type is: DS4.
Firmware version: 8.0
Reset sent to the GIMX adapter.
Current baudrate: 500000 bps.
Trying baudrate: 2000000 bps.
Using baudrate: 2000000 bps.
found pass-through device 0x054c:0x09cc
registered joystick 0 with name "PS4 Controller"
Press the key/button assigned to PS.
```

**`controller type is: DS4`** — the EMUPS4 flash is confirmed end to end, and
the DS4 auth chain is live (`0x054c:0x09cc` = DualShock 4 v2).

### CORRECTION: PlayStation DOES need a button press

An earlier revision of `controls.yaml` and of `ps5_profile_check.py` asserted
that PS4/PS5 need **no** authentication gesture, on the theory that DS4 auth is
pure pass-through. **That was wrong.** GIMX prints:

```
Press the key/button assigned to PS.
```

So a human press is still required to arm the session. What actually differs
from Xbox is only:

| | Xbox One | PS4 / PS5 |
|---|---|---|
| Auth device | genuine MS pad | genuine DualShock 4 |
| Gesture | **HOLD Guide 2 s** | **TAP PS** |
| Optional? | no | **no** |

`auth_gesture` is now `tap_ps` for ps5/ps4 and `hold_guide_2s` for xbox_one.

### Also found: the DS4 config already existed

`ps5.config_file` was `null` and blocking the session guard. The config was
sitting in the GIMX user directory the whole time:

```
%APPDATA%\gimx\config\Dualshock4.xml      <- type="DS4", device "PS4 Controller"
%APPDATA%\gimx\config\Dualshock4_T300RS_PS4.xml
%APPDATA%\gimx\config\XOnePadUsb.xml      <- the old Xbox one
```

`ps5.config_file` and `ps4.config_file` are now set to `Dualshock4.xml`.
Configs live under `%APPDATA%\gimx\config\`, **not** in `C:\Program Files\GIMX`.

### Argument order bites again

The first probe failed with
`Error: At least a config file, an event, or a source IP:port should be
specified` and `now reading arguments for controller #2`. GIMX treats
`--port` as the terminator of the current controller's options, so it must be
**last** — the same trap already recorded in `docs/07-lessons-learned.md`.
`ps5_profile_check.py` now asserts `--port` is the final argument.

---

# Flashing EMUPS4 — RESOLVED 2026-10-30

## Outcome

```
Found programmer: Id = "CATERIN"; type = S
avrdude.exe: Device signature = 0x1e9587 (probably m32u4)
avrdude.exe: 4708 bytes of flash written
avrdude.exe: 4708 bytes of flash verified
```

**EMUPS4 is on the board.** Flashed with
`tools\rig\flash_pounce.ps1`.

## What actually blocked it (two causes, one self-inflicted)

### 1. The "is the port real?" check was KILLING the bootloader
`flash_retry.ps1` originally verified a candidate port by **opening it at
57600 and closing it again**. On an atmega32u4 that open/close can itself
terminate the AVR109 bootloader. The check destroyed the very window it was
testing, and avrdude then met a dead device — which is exactly why the first
attempts printed `programmer is not responding` and
`buffered memory access not supported` *after* apparently finding the board.

**Fix:** never open the port. `GetPortNames()` alone distinguishes a real port
from a `CM_PROB_PHANTOM` node, because phantoms never appear there.

### 2. Output redirection hid every real error
`Start-Process -RedirectStandardOutput/-RedirectStandardError` produced
**empty log files**, so the genuine avrdude error was invisible and the
failure was being diagnosed by guesswork.

**Fix:** run avrdude **inline** with `2>&1`. avrdude writes progress to
stderr, so merging is required. (The `System.Management.Automation.RemoteException`
lines in the output are just PowerShell tagging those stderr records —
harmless.)

### 3. Contributing: a thicket of phantom device nodes
`driver_check.ps1` revealed eight ghost Arduino nodes, all `CM_PROB_PHANTOM`,
including **Micro bootloaders on COM10/COM13 (`PID_0037`)** and a Leonardo
bootloader on COM9 — none of them real. `-PresentOnly` does **not** filter
these, so any tool trusting `Get-PnpDevice` sees a flashable board that isn't
there. `flash_leonardo.ps1` also matches only `PID_0036`, so it would miss a
Micro-style `PID_0037` bootloader entirely.

## Use this from now on

```powershell
powershell -ExecutionPolicy Bypass -File tools\rig\flash_pounce.ps1
# tap RESET when it prints WAITING; add -Force only if avrdude asks for it
```

`flash_leonardo.ps1` is left as-is (it is the documented original), but it has
both weaknesses above. Prefer `flash_pounce.ps1`.

---

# Original investigation notes — observed failures and what they mean

Notes from the PS5 (DualShock 4) migration, 2026-10-30. The rig is otherwise
fully green: GIMX installed, FTDI on COM8 and free, DS4 (`VID_054C&PID_09CC`)
connected, no gimx.exe holding the port.

## The core problem: a ghost COM9

`Get-PnpDevice -PresentOnly` reports:

```
[OK] Ports | Arduino Leonardo bootloader (COM9)
     USB\VID_2341&PID_0036\5&4F0489E&0&4
```

…but `[System.IO.Ports.SerialPort]::GetPortNames()` returns only `COM3, COM8`.

**The PnP node outlives the usable port.** Windows keeps the bootloader device
listed after its ~8 s window closes, so every tool that trusts `-PresentOnly`
(including `flash_leonardo.ps1`) believes the board is ready to flash when it
is not. This is the same class of trap as the ghost devices already documented
in `docs/01-hardware-setup.md`, but worse: `-PresentOnly` does not filter it.

`flash_retry.ps1` now cross-checks `GetPortNames()` **and** opens the port
before launching avrdude.

## Failure signatures, in the order they appeared

### 1. Bootloader expired mid-handshake
```
Found programmer: Id = "?"; type = <
Software Version = D.; Hardware Version = .
avrdude.exe: error: buffered memory access not supported. Maybe it isn't
a butterfly/AVR109 but a AVR910 device?
avrdude.exe: initialization failed, rc=-1
```
avrdude reached *something* and got garbage. The bootloader handed control to
the existing firmware part-way through. **The chip was not written.**

### 2. Ghost port
```
avrdude.exe: ser_open(): can't open device "\\.\COM9":
The system cannot find the file specified.
```
PnP still listed COM9; the port no longer existed.

### 3. No bootloader at all
```
polling for bootloader (up to 7 s)... no bootloader port appeared.
```
After expiry the board stops presenting a COM port entirely.

## What this is NOT

- Not a wrong firmware file — `EMUPS4.hex` is present and preflight-verified.
- Not a missing avrdude — `avrdude.exe` and `avrdude.conf` both found.
- Not a busy port — COM8 is free and no gimx.exe is running.
- Not a wrong board — `VID_2341&PID_0036` is exactly the documented Leonardo
  bootloader ID.

## The fix: a human RESET tap, timed with the poll

The bootloader must be **opened fresh** and avrdude must already be waiting.

```powershell
powershell -ExecutionPolicy Bypass -File tools\rig\flash_retry.ps1
```

When it prints `polling for bootloader`, **tap RESET once** (a double-tap holds
some boards open longer). It polls every 150 ms and launches immediately.

If it keeps losing the race:

| Try | Why |
|---|---|
| A different **data** USB cable | Charge-only cables enumerate nothing; marginal cables drop mid-flash |
| A port **directly on the machine**, no hub | Hubs add enumeration latency that eats the 8 s |
| **Double-tap** RESET | Holds the bootloader open longer on many 32u4 boards |
| Close Arduino IDE / anything scanning serial | A port scanner can grab COM9 the instant it appears |

## Success looks like

```
SUCCESS: EMUPS4 flashed and VERIFIED.
  xxxxx bytes of flash verified
```

The script only reports success when avrdude prints **`flash verified`** —
exit code 0 alone is not trusted, because attempt #1 above exited non-zero
after appearing to "find" a programmer.

## After a verified flash

1. Unplug the Leonardo from the PC, plug it back into the **PS5**.
2. It will **no longer appear as a COM port** — it enumerates as a USB gamepad.
   That absence is correct, not a fault.
3. Confirm GIMX reports `controller type is: DS4` (**not** `XOnePad`).
4. Still blocking input: `ps5.config_file` is `null` in `controls.yaml`, and
   `gimx_session.py` deliberately refuses to start without it.
5. Disable HDCP on the PS5 or the capture card returns blank frames.
