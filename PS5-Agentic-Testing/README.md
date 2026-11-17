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
..\venv\Scripts\python.exe -m ps5agent --dry-run --frames <folder> run scenarios/system_ui/astro_playroom_hub.yaml
```

`--dry-run` serves one frame per action, in file-name order. The run spends 6
actions on setup and preflight (setup `open_home` + `open_games_tab`, the
preflight repeating them, the `triangle` probe and its `down` undo), then one
per step action. Without `--frames` it replays every
file in `tests/fixtures/frames` alphabetically, so expect FAIL. That only shows
the plumbing works.

### 3. On the real PS5

```powershell
cd ..\PS5-Automation-Python
python gimx-session\gimx_session.py start     # TAP PS on the wired DS4 when asked
python tests\prove_input_reaches_ps5.py       # must PASS before any agent run
cd ..\PS5-Agentic-Testing
..\venv\Scripts\python.exe -m ps5agent screens                                  # what screen is this? (no input)
..\venv\Scripts\python.exe -m ps5agent run scenarios/system_ui/astro_playroom_hub.yaml
..\venv\Scripts\python.exe -m ps5agent run --goal "Open Settings and go to System" --type system_ui
..\venv\Scripts\python.exe -m ps5agent suite suites/smoke.yaml                  # add --tag smoke to filter
..\venv\Scripts\python.exe -m ps5agent soak scenarios/soak/astro_playroom_soak.yaml --minutes 5
```

Each run writes `artifacts/runs/<run_id>/`: `report.html`, `result.json`,
`events.jsonl` (every agent step and action), and the before/after `frames/`.
When `learning.enabled` is set, `report.html` also has a **Navigation learning**
table (one row per navigation attempt: source, verdict, the actions tried,
start/end frames and whether the strategy was promoted or invalidated), and
`result.json` carries the same data under `navigation_attempts`. All evidence
links in both files are relative to the run directory, so a run folder stays
viewable after it is moved or copied.
Suites write `artifacts/reports/<ts>-<suite>/` with `suite.html`, `suite.json`
(including LLM call and token totals) and `junit.xml`. The exit code is 0 only
when everything passed.

## Base code vs. game / scenario content

The runner is **game- and scenario-agnostic**. Nothing under `ps5agent/`,
`config/prompts/` or `config/screens/` names a game or a test case; it only
knows the PS5 console (Home, Control Center, search, keyboard, settings) and
generic agent behaviour. Everything specific is data, added only when needed:

| What | Where | Used when |
|---|---|---|
| A test case | `scenarios/<area>/<id>.yaml` | `run` / `suite` / `soak` |
| A group of test cases | `suites/<name>.yaml` | `suite` |
| A game | `config/games/<game>/profile.yaml` (start from `config/games/_template/`) | a scenario sets `game: <game>` |
| In-game screens | `config/games/<game>/screens/*.yaml` | loaded **only** for that game's scenarios, layered on the console screens |
| Offline replay of a scenario | `tests/replays/<scenario_id>.yaml` | `pytest` |
| Console macros | `PS5-Automation-Python/config/controls.yaml` `macros:` | always; the planner/navigator/learner read the list from there |

A game profile can provide: `notes` and `launch` (passed to the planner and
navigator LLMs), `macros` (named sequences, each step still checked by the
ActionGate), `moves` / `combos` / `action_space` / `stop_on` (gameplay agent),
`hud` + `hud_gate` (HUD readers and `expect: {hud: ...}` checks by name),
`forbidden` (per-screen buttons the ActionGate refuses), `dialogs` and
`recover` (recovery agent). Unknown games and scenarios therefore need no
code change.

## Scenarios (ASTRO's PLAYROOM)

All shipped scenarios target the pre-installed PS5 title **ASTRO's PLAYROOM**
and stay in the **system UI**. PS5-native games expect a DualSense and this rig
emulates a DS4, so in-game menus and gameplay are deliberately not automated.

| Scenario | Suite | What it proves |
|---|---|---|
| `system_ui/astro_playroom_hub.yaml` | smoke, regression | tile found on Home (`focus_tile:playroom`), game hub opens, back to Home |
| `system_ui/astro_playroom_search.yaml` | smoke, regression | global search, typing `astro`, the game in results |
| `game_menu/astro_playroom_launch.yaml` | regression | Play Game leaves Home/hub, `home_from_game` returns to Home (game left suspended) |
| `soak/astro_playroom_soak.yaml` | soak | repeated hub round trips under the Monitor |

The game profile is `config/games/astros_playroom/profile.yaml`. No live frames
of this title are recorded yet: `tests/test_scenarios.py` replays each scenario
through the full graph with synthetic frames whose OCR text comes from the
screen signatures. That proves the scenario logic, not the console. Record real
frames on the rig before trusting the `focus_tile` caption match and the
`game_hub` signature for this title.

## Adding a test case

A test case is a YAML scenario in `scenarios/<area>/<id>.yaml`. The file name
must equal `id`.

```yaml
# scenarios/system_ui/astro_playroom_hub.yaml
id: astro_playroom_hub
goal: "Focus the ASTRO's PLAYROOM tile on Home, open its game hub and return Home"
type: system_ui            # system_ui | game_menu | gameplay_scripted | ...
tags: [smoke, system, astro]
setup: [{macro: open_home}, {macro: open_games_tab}]
steps:                     # deterministic: no LLM needed
  - id: focus_tile
    goal: "Focus the ASTRO's PLAYROOM tile on the Home game row"
    actions: [{macro: "focus_tile:playroom"}]
    expect: {text_contains: ["playroom"]}
  - id: open_hub
    goal: "Move down into the ASTRO's PLAYROOM game hub (Play Game button)"
    actions: [{press: down}]
    expect: {screen: game_hub, text_contains: ["playroom"], screen_changed: true}
  - id: back_home
    goal: "Leave the hub and return to the Games tab of Home"
    actions: [{macro: open_home}, {macro: open_games_tab}]
    expect: {screen: home}
teardown: [{macro: open_home}, {macro: open_games_tab}]
limits: {max_steps: 25}
```

Goal-only version (the LLM plans the buttons; needs `ANTHROPIC_API_KEY`):

```yaml
id: astro_playroom_goal
goal: "Open the ASTRO's PLAYROOM game hub from Home, then return home without starting the game"
type: system_ui
tags: [system, llm]
setup: [{macro: open_home}]
teardown: [{macro: open_home}]
limits: {max_steps: 30}
```

- **Actions:** `press` (`times`, `duration`), `hold`, `macro` (from
  `PS5-Automation-Python/config/controls.yaml`, e.g. `open_home`,
  `open_search`, `submit_search`; the rig macros `home_from_game` and
  `focus_tile:<caption_words>[:ps4|ps5]`; or the game profile's `macros`),
  `type: "text"`, `stick`, `trigger`, `combo: <name>`, `wait: <seconds>`.
- **Expect:** `screen` (an id from `config/screens/*.yaml` or the game's
  `screens/`), `text_contains`, `text_absent`, `screen_changed`,
  `vision: "<claim>"` (needs the LLM), and `hud` for games: keys are names from
  the profile's `hud` block (`<presence>: true`, `<bar>_drop_min: 0.1`,
  `<bar>_min: 0.2`).
- **Goal-only steps:** leave out `actions` (or the whole `steps` list, using
  `hints` instead) and the planner/navigator LLM drives. Set `agent:` to
  `navigator`, `typist` or `gameplay`.
- **New screen:** capture a real frame (`python capture\capture.py grab`),
  add `config/screens/<id>.yaml` (console screen) or
  `config/games/<game>/screens/<id>.yaml` (in-game screen) with
  `any_text`/`none_text` taken from that frame's OCR, save the frame to
  `tests/fixtures/frames/`, and add it to `EXPECTED` in
  `tests/test_screens_replay.py`. Never guess signatures.
- **New game:** copy `config/games/_template/` to `config/games/<game>/`, set
  `id`, fill only what the scenarios need, and set `game: <game>` in them.
- **Put it in a suite:** add the path to `suites/smoke.yaml` or
  `suites/regression.yaml`, or create a new `suites/<name>.yaml` whose `name`
  equals the file name.

`tests/test_scenarios.py` validates every scenario, game profile and suite
automatically (ids, screen ids incl. game screens, agents, action syntax,
macro names, suite paths). Run `pytest` after adding one. To also replay it
offline, add `tests/replays/<scenario_id>.yaml` (format in
`tests/replays/README.md`); no test code changes are needed.
