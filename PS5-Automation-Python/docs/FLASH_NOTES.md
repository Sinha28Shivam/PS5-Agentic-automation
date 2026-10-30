# Flashing the Leonardo + verifying the adapter (PS5 / DualShock 4)

All commands run from `PS5-Automation-Python\`.

## 1. Flash EMUPS4

1. Stop any session: `python gimx-session\gimx_session.py stop`
2. Plug the **Leonardo's USB into the PC** (not the PS5) with a **data** cable,
   directly on the machine (no hub).
3. Run the flasher and **tap RESET when it prints WAITING** (double-tap holds
   the ~8 s bootloader window open longer):
   ```powershell
   powershell -ExecutionPolicy Bypass -File flash-leonardo\flash_leonardo.ps1
   ```
4. Success requires avrdude to print `flash verified`:
   ```
   Found programmer: Id = "CATERIN"; type = S
   avrdude.exe: Device signature = 0x1e9587 (probably m32u4)
   avrdude.exe: 4708 bytes of flash verified
   SUCCESS: EMUPS4 flashed and VERIFIED.
   ```
   If avrdude says `buffered memory access not supported`, re-run with `-Force`.

After flashing, plug the Leonardo back into the **PS5**. It will **no longer
appear as a COM port** on the PC; that is correct.

## 2. Verify the adapter

```powershell
powershell -ExecutionPolicy Bypass -File flash-leonardo\adapter_probe.ps1
```

Expected (verified on this rig 2026-10-30):

```
GIMX adapter detected, controller type is: DS4.
Firmware version: 8.0
found pass-through device 0x054c:0x09cc
registered joystick 0 with name "PS4 Controller"
Press the key/button assigned to PS.
```

`controller type is: DS4` confirms EMUPS4. `0x054c:0x09cc` is the DS4 v2 wired
to the PC for auth pass-through.

## Hard-won facts

| Fact | Why it matters |
|---|---|
| **Never open the bootloader port** to "check" it | Opening/closing an AVR109 port can end the bootloader; avrdude then meets a dead device (`programmer is not responding`). The flasher only polls `GetPortNames()`. |
| **Run avrdude inline with `2>&1`** | `Start-Process -Redirect*` produced empty logs and hid every real error. |
| **Ignore `Get-PnpDevice` for bootloader detection** | Phantom (`CM_PROB_PHANTOM`) Leonardo/Micro nodes on COM9/10/13 show up even with `-PresentOnly`. `GetPortNames()` never lists them. |
| **PS5 needs a human PS tap** | GIMX prints `Press the key/button assigned to PS.` Until the wired DS4's PS is tapped, events are accepted and nothing reaches the console. |
| **`--config Dualshock4.xml` is mandatory** | Configs live in `%APPDATA%\gimx\config\`, not Program Files. Without `--config` GIMX forwards nothing, silently. |
| **`--port` must be the LAST GIMX argument** | It terminates the controller's options; anything after it goes to a phantom controller #2. |

## Session start errors

| GIMX output | Meaning / fix |
|---|---|
| `No game controller was found on USB ports.` | No DS4 on the PC. Wire it by USB (not Bluetooth, not to the PS5). |
| `failed to read packet header from the GIMX adapter` | COM8 opened but the Leonardo didn't answer. PS5 must be ON (it powers the Leonardo); unplug/replug the Leonardo from the PS5; check FTDI TX->D0, RX->D1, GND. |
| `controller type is: XOnePad` | Still Xbox firmware. Reflash EMUPS4. |
