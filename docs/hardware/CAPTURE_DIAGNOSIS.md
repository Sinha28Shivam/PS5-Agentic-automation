# Capture card — RESOLVED 2026-10-30

## WORKING. The card was never faulty.

```
1920x1080   frames=90   emptyJPEG=2   png= 780,561B   REAL CONTENT
1280x720    frames=77   emptyJPEG=2   png= 499,452B   REAL CONTENT
640x480     frames=91   emptyJPEG=0   png= 211,042B   REAL CONTENT
```

Frame verified by eye: the **PS5 home screen** at 1920x1080 — Games/Media tabs,
game tiles (Mortal Kombat 11, Astro's Playroom, Minecraft), PlayStation Store,
Console Storage 426.0 GB, clock 13:43. Unmistakably the console, not the
webcam.

Framework preflight now agrees:

```
[OK] capture card connected
[OK] device can be opened (nothing else holding it)
[OK] console video signal present
frame 1920x1080  std=37.72  tones=256
READY - the framework will capture automatically.
```

## What was actually wrong: THE PROBE WAS TOO SHORT

Every earlier check used a 0.4–0.5 s read. `controls.yaml` already documents
this exact behaviour, measured on 2026-08-12:

> After the device is opened, the first ~2 reads come back PERFECTLY FLAT
> (std 0.00) while the card locks onto the HDMI signal. Real content arrives at
> ~1.05 s. Grabbing immediately therefore looks EXACTLY like "no HDMI signal"
> even though the console is on and everything is fine.

So `640x480 / No JPEG data` was the card mid-handshake, not a dead input.
Note `emptyJPEG=2` in the 3-second runs — **exactly the two flat warm-up reads
the config predicts**, followed by 90 good frames.

`capture.py` was always right: it polls up to `sync_timeout: 5.0` rather than
trusting a fixed frame count. My ad-hoc ffmpeg probes bypassed that logic and
reinvented the bug the framework had already solved.

### Lesson

The repo had written down the answer before I started. A diagnostic that is
*less* patient than the production code will manufacture failures that do not
exist. **Any new capture probe must allow >= 1.05 s of sync time**, which
`deep_capture_test.ps1` now does (3 s per mode).

### Corrections to my earlier claims

| I said | Reality |
|---|---|
| "No HDMI signal is arriving" | Signal was present throughout |
| "Check HDMI IN vs OUT — prime suspect" | Cabling was fine |
| "Card's HDMI input stage may be dead (RMA)" | Card is healthy |
| HDCP was blocking capture | Turning HDCP off was still correct and necessary, but it was not what unblocked this |

`1680x1050` returning 0 frames is expected and harmless: the PS5 does not
output that mode, and nothing in this project requests it.

---

# Original investigation notes

## USB link ruled out

```
USB controllers: Intel(R) USB 3.10 eXtensible Host Controller  x2
card offers    : 640x480 ... 1280x720, 1920x1080, 1680x1050 (15 modes)
1920x1080 IS offered -> the USB link can carry 1080p
negotiated     : 640x480     carries data: NO
```

This eliminates the most common false lead. A USB 3.0 card on a USB 2.0 port
still enumerates and still looks healthy, but cannot carry 1080p and parks at a
low fallback mode — indistinguishable from "no signal". **Not the case here:**
both controllers are 3.10 xHCI and the card advertises the full mode list
including 1920x1080.

So the card's USB side and driver are fine. It negotiates `640x480` purely
because it has **nothing on its HDMI input to describe**.

## The question that decides everything: how is the monitor wired?

"The monitor displays the console perfectly" means two very different things:

| Monitor is plugged into | What it proves | Conclusion |
|---|---|---|
| **The card's HDMI OUT** (passthrough) | Signal genuinely flows *through* the card | Card's internal capture path is faulty |
| **The PS5 directly** (or a second PS5 HDMI port / TV) | Only that the PS5 outputs video | Says **nothing** about the card — its HDMI IN may be empty or mis-seated |

The second case is overwhelmingly more common and is consistent with every
measurement so far. A working monitor on a direct cable is *not* evidence the
card is receiving anything.

### The definitive test

Put the monitor on the **card's HDMI OUT** and the PS5 on the **card's
HDMI IN**:

```
PS5 HDMI OUT  ──►  card HDMI IN
card HDMI OUT ──►  monitor
```

- Monitor shows the PS5 **and** capture still empty → the card's capture
  silicon or firmware is at fault (RMA territory).
- Monitor goes black → the signal is not traversing the card at all: wrong
  socket, bad cable, or a dead card input.

Note the ExtremeCap's two HDMI sockets are easy to swap. If the PS5 is in the
card's **OUT**, the monitor still works perfectly via passthrough while the
card captures nothing — exactly the observed symptom.

**Input signal to the PS5 is CONFIRMED WORKING** (verified manually on the TV).
The remaining fault is capture-only.

## Verdict: the card is healthy. There is NO HDMI SIGNAL arriving.

This is **Fault B (no signal)**, not Fault A (device held / driver broken).
The two need opposite fixes, so the distinction matters.

### Evidence the card and driver are fine

```
[OK] Camera        | AVerMedia ExtremeCap UVC   USB\VID_07CA&PID_0110&MI_00
[OK] MEDIA         | AVerMedia ExtremeCap UAC
[OK] USB           | USB Composite Device
ErrorCode CM_PROB_NONE   (every node)
```

- Windows camera privacy: **Allow** at HKCU, HKLM *and* `NonPackaged`
  (desktop apps), so OpenCV/ffmpeg are not being blocked by policy.
- ffmpeg enumerates it by name and **successfully opens it**.
- It advertises a full, healthy format list — mjpeg up to
  `1920x1080 @ 25–60 fps`.

### Evidence there is no signal

```
mjpeg 1920x1080        8,699 bytes   BLACK / flat
default (no hints)     2,013 bytes   BLACK / flat
[mjpeg] No JPEG data found in image
[mjpeg] Found EOI before any SOF, ignoring
```

The device **opens and returns frames**, but the MJPEG pin carries no actual
data. `Found EOI before any SOF` means an empty JPEG — a frame envelope with
nothing in it. That is a card with no video input, not a software fault.

`yuyv422` reporting "format unsupported" is expected and harmless: this card
is **MJPEG-only**, per its own option list.

## Fix, in order of likelihood

1. **HDCP — the #1 cause on PS5.** The PS5 encrypts its system UI over HDMI,
   and the card refuses to pass protected content.
   **Settings → System → HDMI → Enable HDCP → OFF.** The UI restarts.
2. **Wrong socket.** PS5 `HDMI OUT` must go to the card's **HDMI IN**, not its
   passthrough `HDMI OUT`.
3. **PS5 asleep / rest mode.** Wake it; confirm the TV is live.
4. **Output mode the card cannot ingest.** This is a 1080p60 class device —
   if the PS5 is pushing 4K, 120 Hz or VRR, force **1080p / 60 Hz** while
   bringing the rig up.

## A trap to avoid

`index 1` probes as `1280x720, std 1.58`. **That is the HP HD Camera, not the
console.** Do not "fix" a blank capture by switching `opencv_index` to 1 — you
would be testing the framework against your own webcam, which already happened
once (see the capture notes in `controls.yaml`, 2026-08-14). `capture.py`
resolves the device **by name** precisely to prevent this.

## Note on Microsoft Teams

Two `ms-teams` processes were running. Teams does grab camera devices and
**must be closed before scripted runs**, but it is *not* the current cause:
ffmpeg opened the device successfully while Teams was running. Close it
anyway before using `capture.py`, which holds the device for the whole session.

`RECentralService` is only AVerMedia's background service — it is the
**RECentral GUI** that takes exclusive ownership.

## Re-check after changing HDCP

```powershell
powershell -ExecutionPolicy Bypass -File tools\rig\grab_by_name.ps1
```

A real 1080p frame is typically **> 100 KB**. Anything under ~12 KB is still
black. Then:

```bash
cd PS5-Automation-Python && python capture\capture.py preflight
python tools/rig/prove_input_reaches_ps5.py
```

## Tools added

| Script | Purpose |
|---|---|
| `capture_diagnose.ps1` | Hardware, driver error codes, holders, privacy policy, device names |
| `grab_by_name.ps1` | One ffmpeg frame **by name** (never by index) |
| `capture_formats.ps1` | Enumerates formats and tests each for real pixels |
