# PS5 agentic rebuild — what was removed, kept, and still to do

Executed 2026-10-30. Scope chosen: **agentic only**.

## Removed (658 files)

| Path | Files | Why |
|---|---|---|
| `Xbox-Agentic-Testing/` | 638 | Entire Xbox agent layer: agents, graph, tools, gameplay, Xbox screen signatures, Xbox keyboard layouts, Xbox routes, Minecraft/Dungeons profiles, recorded Xbox run artifacts, lessons and test fixtures |
| `docs/` | 12 | Xbox hardware + agent documentation (00–11) |
| `scripts/` | 8 | Xbox-era helpers |
| `README.md` | 1 | Described the Xbox two-layer project |
| `.github/workflows/offline-tests.yml` | 1 | Every path it referenced was deleted |

## Kept

| Path | Why |
|---|---|
| `PS5-Automation-Python/` → `PS5-Automation-Python/` | **Hardware-verified on PS5 today.** The folder name was Xbox; the code is not. |
| `tools/rig/` | PS5 rig tooling: flasher, probes, capture diagnostics, input proof |

The hardware layer is already PlayStation-native:
`controls.yaml` has `ps5`/`ps4` profiles (`gimx_type: DS4`, `firmware:
EMUPS4`, `config_file: Dualshock4.xml`, `auth_gesture: tap_ps`), canonical
PlayStation button names with Xbox names kept only as aliases, and no
`XOnePad` fallbacks anywhere.

## Backups (this was irreversible, so two exist)

1. **Branch `ps5-backup-before-agentic-wipe`**, commit `cf79d14` — the full
   repo including the Xbox agentic layer and all PS5 edits.
   ```bash
   git checkout ps5-backup-before-agentic-wipe
   ```
2. **`C:\Users\sinha\Desktop\InstrumentsStore\PS5-RIG-TOOLS-BACKUP`** — 62
   files. Needed because `.gitignore:39 (TEMP_*)` excludes `temp_code_test/`
   from git entirely, so the rig tooling and the proof frames were **not** in
   the backup commit.

## Repo reorganisation (2026-10-30, done)

| Before | After |
|---|---|
| `Xbox-Automation-Python/` | `PS5-Automation-Python/` (rename complete; `rename_hw.ps1` deleted) |
| `temp_code_test/hardware/*.ps1, *.py` (gitignored) | `tools/rig/` (committed) |
| `temp_code_test/hardware/*.md` | `docs/hardware/` |
| `temp_code_test/artifacts/capture-check/framework-grab.png` | `docs/hardware/reference/ps5-home-1080p.png` |
| other `temp_code_test/artifacts/*.png` | deleted (copies in `PS5-RIG-TOOLS-BACKUP`) |
| empty `.github/workflows/` | deleted |

Also: `xbox_one` / `xbox_360` profiles dropped from `controls.yaml`; the
flasher now defaults to `EMUPS4`; the GIMX auth banner says *tap PS* and
`gimx_session.py` now recognises the DS4 prompt
`Press the key/button assigned to PS.`. Rig scripts write output to
`artifacts/rig/` (gitignored).

> Do not run GIMX as administrator. Elevated it claims REALTIME priority and
> grabs input devices — that froze a PC during this project's development.
> `gimx_session.py` deliberately passes `--nograb`, `--timeout` and pins
> priority to Normal.

## Scaffolded so far

```
PS5-Agentic-Testing/
├── README.md                      - what this is, what was kept, PS5 limits
├── REBUILD_NOTES.md               - this file
└── config/
    ├── settings.yaml              - PS5 paths, DS4 profile, auth + HDCP facts
    └── screen_signatures.yaml     - PS5 screens; placeholders marked UNVERIFIED
```

`settings.yaml` points `automation_root` and `controls_config` at
`../PS5-Automation-Python`, so it is already correct for the post-rename
layout.

## Deliberately NOT carried over

| Xbox artefact | Why it would have been harmful |
|---|---|
| `screen_signatures.yaml` (`"my games & apps"`, `"buy $"`, `"join game pass"`) | None appear on PS5; the executor's blind-tap guard would silently stop guarding |
| `xbox_global_search_en` keyboard layout | PS5's on-screen keyboard differs in rows, origin and symbol toggle; typing would land on wrong characters |
| `config/routes/*.route.json` | Baked Xbox sequences (`guide → b → y → type…`) |
| Minecraft / Dungeons / Max game profiles | Xbox titles, not part of PS5 testing |
| `artifacts/lessons/*`, `tests/fixtures/runs/*` | Thousands of lines of recorded Xbox screen text that would teach the planner Xbox behaviour |

The new `screen_signatures.yaml` starts with `verified: false` and only two
lists populated from the **real 1080p PS5 frame captured today** (`playstation
store`, `games`, `media`, `console storage`, `recently played`, `friend
activity`, `game catalogue`). Everything else is an explicit empty list with a
comment saying to capture a frame rather than guess.

## Next steps, in order

1. Re-verify the hardware layer after the rename:
   ```powershell
   powershell -File tools\rig\manual_check.ps1
   cd PS5-Automation-Python; python capture\capture.py preflight
   ```
2. Reconnect the DS4 **by cable**, start a session, **tap PS**, then get the
   first full PASS:
   ```bash
   python tools/rig/prove_input_reaches_ps5.py
   ```
3. Only then build agents — and derive every screen signature and keyboard
   layout from real captured PS5 frames.
