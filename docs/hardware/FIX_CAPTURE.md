# Fixing the capture path — status and exact steps

## Where we are now (after you turned HDCP off)

| Check | Result |
|---|---|
| Card + driver | ✅ healthy, `CM_PROB_NONE` on every node |
| Camera privacy (incl. desktop apps) | ✅ Allow |
| Device free? | ✅ yes — Teams closed, RECentral already exited |
| **Signal arriving?** | ❌ **still none** |

```
RESOLUTION : 640x480
FRAME RATE : 59.94 fps
CODEC      : mjpeg
[mjpeg] Found EOI before any SOF, ignoring
[mjpeg] No JPEG data found in image
```

### Why `640x480` is the tell

That is **not** the PS5 sending VGA. `640x480` is the **lowest format in the
card's own option list**, which is what a UVC device falls back to when it has
**no input to describe**. Paired with `No JPEG data found`, it means the card
is awake and being read but has nothing on its HDMI IN.

So: HDCP off was necessary, but it was not the only problem.

---

## Fix in this order

### 1. Confirm the cable is in **HDMI IN**, not HDMI OUT

The ExtremeCap has two HDMI sockets and they are easy to mix up.

```
PS5  HDMI OUT  ──►  card HDMI IN      <-- REQUIRED
card HDMI OUT  ──►  TV               <-- optional passthrough
```

If the PS5 is in the card's **OUT**, the TV still works perfectly and the card
captures nothing — which matches exactly what you are seeing.

### 2. Wake the PS5 and keep it awake

Rest mode drops the HDMI signal. The orange standby light means no output.
Also disable auto-sleep while testing:
**Settings → System → Power Saving → Set Time Until PS5 Enters Rest Mode →
"Don't Put in Rest Mode"**.

### 3. Set the output to 1080p (your question)

**Settings → Screen and Video → Video Output**

| Setting | Set to | Why |
|---|---|---|
| **Resolution** | **1080p** | This card is a 1080p-class device; 4K is not ingested |
| **HDR** | **Off** | HDR metadata on an SDR capture path = black or washed-out frames |
| **120 Hz Output** | **Off / Automatic→off** | 120 Hz is outside the card's `25–60 fps` list |
| **VRR** | **Off** | Variable refresh confuses fixed-rate capture |
| **Deep Colour Output** | **Off** while debugging | Avoids a colour-depth mismatch |
| **Enable HDCP** (System → HDMI) | **Off** | ✅ already done |

> Do **not** use "Automatic" for Resolution while bringing the rig up. It
> renegotiates and can pick a mode the card cannot take.

A forced-1080p safe mode, if the screen is blank on the TV too:
power off fully, then hold the power button until the **second** beep to boot
into Safe Mode → *Change Video Output* → *Change Resolution* → **1080p**.

### 4. Cable quality

Use the cable that shipped with the PS5 or another certified High Speed one,
directly between PS5 and card — **no adapters, splitters or long runs** while
debugging.

---

## Verify after each change

```powershell
# 1. is any resolution arriving at all?
powershell -ExecutionPolicy Bypass -File tools\rig\check_input_resolution.ps1
```

Target:

```
RESOLUTION : 1920x1080
FRAME RATE : 59.94 fps   (or 60)
CODEC      : mjpeg
CORRECT - 1080p, exactly what controls.yaml expects.
```

Still `640x480` + `No JPEG data` ⇒ signal still absent; re-check steps 1–2.

```powershell
# 2. grab a real picture and LOOK at it
powershell -ExecutionPolicy Bypass -File tools\rig\grab_by_name.ps1
```

A real 1080p frame is usually **> 100 KB**. Under ~12 KB is still black.

```bash
# 3. the framework's own check
cd PS5-Automation-Python && python capture\capture.py preflight

# 4. the full proof (needs a GIMX session + PS tap)
python tools/rig/prove_input_reaches_ps5.py
```

---

## Working practice

- **RECentral 4 is useful** for confirming by eye that video arrives, and it
  displays the input resolution. **But close it before any scripted run** —
  only one app may hold a capture device. It also minimises to the **system
  tray** rather than exiting, so check there.
- **Teams grabs camera devices on launch.** Two instances were holding handles;
  both are now stopped. Keep it closed during runs.
- `RECentralService` is only AVerMedia's background service — harmless, leave it.

```powershell
# report holders
powershell -ExecutionPolicy Bypass -File tools\rig\free_capture.ps1
# ...and actually close them
powershell -ExecutionPolicy Bypass -File tools\rig\free_capture.ps1 -Close
```

## Never "fix" this by changing the index

Index 1 is the **HP HD Camera**. Switching `capture.opencv_index` to 1 makes
the blank-screen error disappear and silently tests the framework against your
webcam — which already happened once (`controls.yaml` capture notes,
2026-08-14). `capture.py` resolves the device **by name** for this reason.
Leave `auto_detect_device: true`.
