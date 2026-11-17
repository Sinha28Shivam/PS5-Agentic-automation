# Scenario replay specs

One `<scenario_id>.yaml` per scenario you want replayed offline through the full
agent graph (`tests/test_scenarios.py::test_replay`). The test code is generic;
everything scenario- or game-specific lives here.

```yaml
scenario: scenarios/<area>/<id>.yaml     # scenario under test
screens:                                 # name -> OCR text the fake rig shows
  home: "games media console storage ..."
cases:
  - name: pass
    frames: [home, home, ...]            # frame 0 = start, frame k = after action k
    verdict: PASS                        # default PASS; anything else = must not pass
    steps: [step_a, step_b]              # optional: expected plan step ids
    step_verdicts: {step_b: FAIL}        # optional: PASS / non-PASS per step
    skip_actions: 6                      # optional: ignore setup + preflight actions
    actions: ["press:down"]              # optional: must appear in this order
```

Every run spends six actions before the first step: setup (`open_home`,
`open_games_tab`), the preflight repeating that setup, then the `triangle`
input probe and its `down` undo. A `wait` action does not advance the frame.
Take screen text from the phrases in `config/screens/*.yaml` (or the game's
`config/games/<game>/screens/`) so the real classifier is exercised.