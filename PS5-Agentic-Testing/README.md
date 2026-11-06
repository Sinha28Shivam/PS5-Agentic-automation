# PS5-Agentic-Testing

Fresh agentic layer for **PlayStation 5** console testing. Rebuilt from zero on
2026-10-30; it shares no code, config or artifacts with the previous Xbox
agentic layer.

## Why this was rebuilt rather than ported

The old `Xbox-Agentic-Testing` was correct for an Xbox One and wrong for a PS5
in ways that were not cosmetic:

- **Screen signatures** keyed on `"my games & apps"`, `"buy $"`,
  `"join game pass"` — the executor's safety guard would mis-fire on every PS5
  screen and abort runs.
- **Keyboard layouts** (`xbox_global_search_en`) encoded Xbox's on-screen
  keyboard geometry; PS5's differs in rows, origin and symbol toggle.
- **Routes** were baked Xbox button sequences (`guide → b → y → type...`).
- **Game profiles** targeted Xbox titles (Minecraft Dungeons, Max: The Curse of
  Brotherhood) that are not part of PS5 testing.
- **Lessons / artifacts / test fixtures** were thousands of lines of recorded
  Xbox screen text, which would have taught the planner Xbox behaviour.

Carrying that forward would mean an agent layer that *looks* configured and is
quietly wrong — the exact failure class this project has already paid for.

## What was kept

The **hardware layer** (`PS5-Automation-Python/`) was NOT rebuilt. It is
already PlayStation-native and hardware-verified on this rig:

```
GIMX adapter detected, controller type is: DS4.
Firmware version: 8.0
found pass-through device 0x054c:0x09cc
registered joystick 0 with name "PS4 Controller"
capture: 1920x1080  std=37.7  tones=256
```

Its `controls.yaml` has PlayStation-canonical names (`cross`, `circle`, `ps`,
`options`, `share`, `l1`, `r2`, ...) with the Xbox names retained only as
backward-compatible aliases.

## Status

| Layer | State |
|---|---|
| Hardware: input (DS4 via GIMX/Leonardo) | ✅ verified on hardware |
| Hardware: capture (1080p) | ✅ verified on hardware |
| Agentic: this directory | ✅ multi-agent runner implemented; offline tests pass |

## Known PS5 constraints (inherited, not solved)

1. **DualShock 4 only.** GIMX cannot emulate a DualSense, so only
   PS4-compatible titles accept this adapter. PS5-native games reject it.
2. **Auth needs a human.** A genuine DS4 must be wired to the PC *before* the
   session starts, and someone must TAP **PS** when GIMX prints
   `Press the key/button assigned to PS.`
3. **HDCP must be off** (Settings → System → HDMI) or capture returns blank
   frames.
4. **One capture consumer.** Close the RECentral GUI and Teams before any run.

## The rule this layer is built around

Accepting an event proves nothing. Only an observed change on the capture card
proves the console reacted. A run with no visual evidence is **BLOCKED**, never
PASS.

## Running it manually

All commands run from `PS5-Agentic-Testing\` with the repo venv.

### 1. Install (once)

```powershell
..\venv\Scripts\python.exe -m pip install -r ..\PS5-Automation-Python\requirements.txt -r requirements.txt
```

Tesseract OCR must be installed on the system. Put `ANTHROPIC_API_KEY=` in the
repo-root `.env` (see `.env.example`). It is only needed for goal-only steps and
`vision:` checks; scenarios whose steps all have `actions` run without it.

### 2. Offline (no PS5)

```powershell
..\venv\Scripts\python.exe validate_config.py          # config sanity
..\venv\Scripts\python.exe -m pytest -q                # all unit + replay tests
..\venv\Scripts\python.exe -m ps5agent graph           # print the agent graph (mermaid)
# Replay a scenario through the full graph using frames from a folder:
..\venv\Scripts\python.exe -m ps5agent --dry-run --frames <folder> run scenarios/system_ui/home_navigation.yaml
```

`--dry-run` serves one frame per action, in file-name order. The run spends 4
frames on setup and preflight (`open_home`, `open_home`, `ps` probe,
`circle` undo), then one per step action. Without `--frames` it replays every
file in `tests/fixtures/frames` alphabetically, so expect FAIL. That only shows
the plumbing works.

### 3. On the real PS5

```powershell
cd ..\PS5-Automation-Python
python gimx-session\gimx_session.py start     # TAP PS on the wired DS4 when asked
python tests\prove_input_reaches_ps5.py       # must PASS before any agent run
cd ..\PS5-Agentic-Testing
..\venv\Scripts\python.exe -m ps5agent screens                                  # what screen is this? (no input)
..\venv\Scripts\python.exe -m ps5agent run scenarios/system_ui/home_navigation.yaml
..\venv\Scripts\python.exe -m ps5agent run --goal "Open Settings and go to System" --type system_ui
..\venv\Scripts\python.exe -m ps5agent suite suites/smoke.yaml                  # add --tag smoke to filter
..\venv\Scripts\python.exe -m ps5agent soak scenarios/soak/home_soak.yaml --minutes 5
```

Each run writes `artifacts/runs/<run_id>/`: `report.html`, `result.json`,
`events.jsonl` (every agent step and action), and the before/after `frames/`.
Suites write `artifacts/reports/<ts>-<suite>/` with `suite.html`, `suite.json`
(including LLM call and token totals) and `junit.xml`. The exit code is 0 only
when everything passed.

## Adding a test case

A test case is a YAML scenario in `scenarios/<area>/<id>.yaml`. The file name
must equal `id`.

```yaml
# scenarios/system_ui/control_center.yaml (verified on hardware)
id: control_center
goal: "Open the Control Center with PS and close it with Circle"
type: system_ui            # system_ui | game_menu | gameplay_scripted | ...
tags: [smoke, system]
setup: [{macro: open_home}]
steps:                     # deterministic: no LLM needed
  - id: open_cc
    goal: "Open the Control Center"
    actions: [{press: ps}]
    expect: {screen: control_center, screen_changed: true}
  - id: close_cc
    goal: "Close the Control Center"
    actions: [{press: circle}]
    expect: {screen: home, screen_changed: true}
limits: {max_steps: 15}
```

Goal-only version (the LLM plans the buttons; needs `ANTHROPIC_API_KEY`):

```yaml
id: settings_console_info
goal: "Open Settings and navigate to the System page, then return home without changing anything"
type: system_ui
tags: [regression, system, llm]
setup: [{macro: open_home}]
teardown: [{macro: open_home}]
limits: {max_steps: 30}
```

- **Actions:** `press` (`times`, `duration`), `hold`, `macro` (from
  `PS5-Automation-Python/config/controls.yaml`, e.g. `open_home`,
  `open_search`, `submit_search`), `type: "text"`, `stick`, `trigger`,
  `wait: <seconds>`.
- **Expect:** `screen` (an id from `config/screens/*.yaml`),
  `text_contains`, `text_absent`, `screen_changed`, `vision: "<claim>"` (needs
  the LLM), and `hud` for games.
- **Goal-only steps:** leave out `actions` (or the whole `steps` list, using
  `hints` instead) and the planner/navigator LLM drives. Set `agent:` to
  `navigator`, `typist` or `gameplay`.
- **New screen:** capture a real frame (`python capture\capture.py grab`),
  add `config/screens/<id>.yaml` with `any_text`/`none_text` taken from that
  frame's OCR, save the frame to `tests/fixtures/frames/`, and add it to
  `EXPECTED` in `tests/test_screens_replay.py`. Never guess signatures.
- **Put it in a suite:** add the path to `suites/smoke.yaml` or
  `suites/regression.yaml`, or create a new `suites/<name>.yaml` whose `name`
  equals the file name.

`tests/test_scenarios.py` validates every scenario and suite automatically
(ids, screen ids, agents, action syntax, suite paths). Run `pytest`
after adding one. To also replay it offline, copy `test_replay_home_navigation`
in that file and give it the frame sequence the run should see.
