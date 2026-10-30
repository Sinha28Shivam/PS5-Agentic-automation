"""
compare_proof_frames.py - measure the before/after frames from an input proof.

    python tools/rig/compare_proof_frames.py

Re-reads the saved frames and reports the same metric the framework uses, plus
WHERE the change is, so a real highlight move can be told apart from a clock
tick or a carousel animation. Those background animations are the reason a
whole-frame delta alone can be misleading on the PS5 home screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "PS5-Automation-Python" / "capture"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from capture import difference, frame_stats  # noqa: E402

PROOF = REPO_ROOT / "artifacts" / "rig" / "input-proof"


def main() -> int:
    before_p = PROOF / "1-before.png"
    after_p = PROOF / "2-after.png"
    for p in (before_p, after_p):
        if not p.is_file():
            print(f"MISSING: {p}")
            return 2

    before = cv2.imread(str(before_p))
    after = cv2.imread(str(after_p))

    print("=" * 66)
    print("  INPUT PROOF - FRAME COMPARISON")
    print("=" * 66)
    for name, f in (("before", before), ("after", after)):
        s = frame_stats(f)
        print(f"  {name:<7} {f.shape[1]}x{f.shape[0]}  "
              f"std={s['std']:.2f}  tones={int(s['tones'])}")

    delta = difference(before, after)
    print(f"\n  WHOLE-FRAME DELTA = {delta:.4f}")

    # Where did it change? The PS5 home screen animates on its own (clock,
    # store carousel), so localise the change before trusting it.
    gb = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    ga = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gb, ga)

    h, w = diff.shape
    regions = {
        "game tile row (highlight)": (0.00, 0.10, 1.00, 0.20),
        "clock / top-right":        (0.80, 0.00, 0.20, 0.10),
        "widgets lower half":       (0.00, 0.45, 1.00, 0.55),
        "store carousel (right)":   (0.60, 0.45, 0.40, 0.45),
    }
    print("\n  WHERE THE CHANGE IS")
    for label, (rx, ry, rw, rh) in regions.items():
        x0, y0 = int(rx * w), int(ry * h)
        x1, y1 = int((rx + rw) * w), int((ry + rh) * h)
        sub = diff[y0:y1, x0:x1]
        print(f"    {label:<28} mean={float(sub.mean()):7.4f}  "
              f"max={int(sub.max()):3d}  changed>30={int((sub > 30).sum()):,}")

    changed = int((diff > 30).sum())
    pct = 100.0 * changed / diff.size
    print(f"\n  strongly-changed pixels: {changed:,} ({pct:.4f}% of frame)")

    out = PROOF / "3-diff.png"
    cv2.imwrite(str(out), cv2.applyColorMap(
        cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
        cv2.COLORMAP_JET))
    print(f"  diff heatmap saved: {out}")

    print("\n" + "=" * 66)
    tile = diff[int(0.10 * h):int(0.30 * h), :]
    tile_changed = int((tile > 30).sum())
    if tile_changed > 500:
        print("  VERDICT: the GAME TILE ROW changed -> the highlight MOVED.")
        print("  Input reached the PS5.")
        return 0
    if delta >= 0.5:
        print("  VERDICT: the frame changed, but NOT in the tile row.")
        print("  That is most likely the PS5's own animation (clock ticking,")
        print("  store carousel) - NOT evidence that input arrived.")
        return 1
    print("  VERDICT: no meaningful change. Input did NOT reach the console,")
    print("  or the screen could not react to it.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
