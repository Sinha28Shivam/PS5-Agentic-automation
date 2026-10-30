"""
prove_input_reaches_ps5.py - the ONLY honest test that input reaches the PS5.

    python tests/prove_input_reaches_ps5.py
    python tests/prove_input_reaches_ps5.py --button right --times 4

WHY THIS SCRIPT EXISTS
----------------------
"GIMX accepted the event" is NOT proof. An unauthenticated or mis-wired session
accepts every event, prints "ok", and delivers nothing. This project already
lost hours to exactly that (see docs/HOW_TO_TEST_SIGNAL.md): six cheerful successes
in a row while the TV never moved.

The only proof is a PIXEL CHANGE on the capture card:

    grab frame BEFORE  ->  send input  ->  grab frame AFTER  ->  compare

If the screen did not change, the input did not arrive. This script therefore
refuses to report success on anything weaker.

WHAT IT CANNOT TELL YOU
-----------------------
A no-change result has two causes it cannot separate:
  1. the input never reached the console, or
  2. the input arrived but the current screen has no visible response.
That is why it presses a NAVIGATION button on a menu by default - a highlight
move is the most reliably visible reaction available.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HW_ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = HW_ROOT
sys.path.insert(0, str(AUTOMATION / "test-controller"))
sys.path.insert(0, str(AUTOMATION / "gimx-session"))
sys.path.insert(0, str(AUTOMATION / "capture"))

import cv2                                       # noqa: E402
from capture import (ScreenCapture, difference,   # noqa: E402
                     frame_stats, is_blank, preflight)
from gimx_session import session_is_up            # noqa: E402
from test_controller import ConsolePad            # noqa: E402

OUT_DIR = HW_ROOT / "artifacts" / "input-proof"

# DS4 v1 = 054C:05C4, DS4 v2 = 054C:09CC. DualSense (0CE6) is NOT usable by
# GIMX for authentication, so it deliberately does not count here.
_DS4_IDS = ("VID_054C&PID_05C4", "VID_054C&PID_09CC")


def _ds4_present() -> bool:
    """True if a genuine DualShock 4 is attached to this PC."""
    import subprocess
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty InstanceId"],
            capture_output=True, text=True, timeout=25)
    except (subprocess.TimeoutExpired, OSError):
        # Unknown rather than absent - do not block the run on a probe failure.
        print("    (could not query USB devices; continuing)")
        return True
    ids = (res.stdout or "").upper()
    return any(pid in ids for pid in _DS4_IDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--button", default="right",
                    help="control to press (default: right - a visible nav move)")
    ap.add_argument("--times", type=int, default=3)
    ap.add_argument("--interval", type=float, default=0.6,
                    help="pause between presses (animated menus eat fast input)")
    ap.add_argument("--settle", type=float, default=1.2,
                    help="seconds to wait after input before the AFTER frame")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="mean abs pixel diff that counts as 'the screen moved'")
    ap.add_argument("--console", default=None, help="console profile (default: ps5)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  PROVE INPUT REACHES THE PS5")
    print("=" * 70)

    # ---- 1. the session must be reachable --------------------------------
    print("\n[1] GIMX session")
    if not session_is_up(quiet=True):
        print("    FAIL: no GIMX session reachable at 127.0.0.1:51914")
        print("    Start one:  python gimx-session/"
              "gimx_session.py start")
        return 2
    print("    reachable (NOTE: reachable != authenticated != delivering)")

    # ---- 1b. the auth device must be attached ----------------------------
    # session_is_up() only proves UDP reachability. On 2026-10-30 this script
    # ran a full before/after against a session whose DualShock 4 had left the
    # PC: GIMX reported healthy, accepted every event, delivered none, and the
    # run burned a capture cycle to discover nothing. Check the pad FIRST.
    print("\n[1b] DualShock 4 (authentication pass-through)")
    if not _ds4_present():
        print("    FAIL: no DualShock 4 found on this PC.")
        print("    GIMX authenticates PS4/PS5 by pass-through from a GENUINE")
        print("    DS4 wired to the PC. Without it the session can never arm:")
        print("    events are accepted, report ok, and reach nothing.")
        print("    If it paired to the PS5 over Bluetooth, hold PS + SHARE to")
        print("    unpair, cable it to the laptop, then RESTART the session -")
        print("    a session started without the pad stays dead.")
        return 7
    print("    present")

    # ---- 2. the capture card must be usable -------------------------------
    print("\n[2] Capture card")
    pf = preflight(quiet=True)
    if not pf.device_opens:
        print("    FAIL: cannot open the capture device.")
        for m in pf.messages:
            print(f"    {m}")
        if pf.conflicts:
            print(f"    CLOSE THESE FIRST: {', '.join(pf.conflicts)}")
        print("\n    Without the capture card there is NO way to prove input")
        print("    arrived. Refusing to guess.")
        return 3
    print("    device opens")
    return _run(args)


def _run(args) -> int:
    """before -> input -> after -> compare. The actual experiment."""
    with ScreenCapture() as cam:
        print("\n[3] BEFORE frame")
        before = cam.grab(allow_blank=True)
        if before is None:
            print("    FAIL: no frame at all")
            return 4
        s = frame_stats(before)
        print(f"    {before.shape[1]}x{before.shape[0]}  "
              f"std={s['std']:.2f}  tones={int(s['tones'])}")

        if is_blank(before):
            cv2.imwrite(str(OUT_DIR / "before-BLANK.png"), before)
            print("    FAIL: the frame is BLANK (a flat image = no signal).")
            print("    On PS5 the usual cause is HDCP on the system UI:")
            print("      Settings > System > HDMI > Enable HDCP  ->  OFF")
            print("    A blank frame cannot prove anything, so stopping here.")
            return 5

        before_path = OUT_DIR / "1-before.png"
        cv2.imwrite(str(before_path), before)
        print(f"    saved {before_path}")

        # ---- 4. send the input -------------------------------------------
        print(f"\n[4] Sending: {args.button} x{args.times}")
        pad = ConsolePad(console=args.console)
        print(f"    profile emulates: --type {pad.ctype}")
        ok = pad.press_times(args.button, args.times, interval=args.interval)
        print(f"    GIMX accepted: {ok}   <- this alone proves NOTHING")

        time.sleep(args.settle)

        # ---- 5. after frame ----------------------------------------------
        print("\n[5] AFTER frame")
        after = cam.grab(allow_blank=True)
        if after is None:
            print("    FAIL: no frame after input")
            return 6
        after_path = OUT_DIR / "2-after.png"
        cv2.imwrite(str(after_path), after)
        print(f"    saved {after_path}")

        delta = difference(before, after)

    # ---- 6. the verdict ----------------------------------------------------
    print("\n" + "=" * 70)
    print(f"  SCREEN DELTA = {delta:.3f}   (threshold {args.threshold})")
    print("=" * 70)

    if delta >= args.threshold:
        print("  PASS - the screen CHANGED.")
        print("  Input is reaching the PS5. The path works end to end:")
        print("    python -> gimx client -> UDP -> gimx server -> COM8")
        print("           -> FTDI -> Leonardo (EMUPS4/DS4) -> PS5")
        return 0

    print("  FAIL - the screen did NOT change.")
    print()
    print("  Two possible causes, which this test cannot separate:")
    print("    (a) the input never reached the console, or")
    print("    (b) it arrived but this screen has no visible reaction.")
    print()
    print("  Check in this order:")
    print("    1. Was PS TAPPED on the real DualShock 4 after GIMX printed")
    print("       'Press the key/button assigned to PS.'? Without it the")
    print("       session accepts everything and delivers nothing.")
    print("    2. Is the DualShock 4 still WIRED to the PC? If it paired to")
    print("       the PS5 over Bluetooth it LEFT the PC and auth died.")
    print("    3. Is the PS5 on a menu with a visible highlight? A static")
    print("       screen cannot show a d-pad move.")
    print(f"    4. Compare the frames yourself: {OUT_DIR}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
