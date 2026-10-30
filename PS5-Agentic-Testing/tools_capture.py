"""Live capture helper: run steps, save frame to tests/fixtures/frames/<name>.jpg + full png."""
import sys, time, cv2
from ps5agent.hw.adapters import Rig
from ps5agent.core.state import Action
from ps5agent.hw.adapters import perform
name, steps = sys.argv[1], sys.argv[2:]
rig = Rig()
for s in steps:
    if s.startswith("wait="): time.sleep(float(s[5:])); continue
    if s.startswith("macro="): rig.macro(s[6:]); time.sleep(0.8); continue
    if s.startswith("type="): rig.type_text(s[5:].replace("_"," ")); continue
    if s.startswith("hold="):
        b, d = s[5:].split(":"); rig.hold(b, float(d)); time.sleep(0.6); continue
    rig.press(s); time.sleep(0.6)
time.sleep(1.2)
f = rig.grab(); rig.close()
cv2.imwrite(f"tests/fixtures/frames/{name}.jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 88])
cv2.imwrite(f"artifacts/capture_{name}_small.jpg", cv2.resize(f, (960, 540)))
print("saved", name)
