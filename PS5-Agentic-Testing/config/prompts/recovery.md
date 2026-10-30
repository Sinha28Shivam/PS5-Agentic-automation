# PS5 recovery

The test lost its way. Get the console back to a known, safe screen (Home, or the
step's expected screen) with the fewest harmless inputs.

## Escalation ladder (follow in order)
1. Store / purchase / account prompt on screen -> `circle` x2. Never `cross`, `r2`,
   `options` or typing there.
2. `circle` up to 3 times, checking the screen after each (closes menus, Control
   Center, search, keyboard).
3. macro `open_home` (circle x3 with pauses; harmless on Home).
4. In a game: the game profile's `recover` actions (e.g. pause menu -> quit to
   main menu). MK11: R2 on the main menu opens the STORE - forbidden.

## Rules
- Never confirm dialogs while recovering (no `cross` on delete / sign-out /
  initialise / purchase prompts).
- `ps` opens the Control Center; it does not go Home by itself - follow with `circle`.
- If the screen does not change after several presses, input may not be delivered:
  stop and report BLOCKED rather than pressing more.

## Reply (JSON only)
```json
{"actions": [{"press": "circle", "times": 2}], "reason": "store page open", "give_up": false}
```
