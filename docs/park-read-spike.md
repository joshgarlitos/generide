# Spike: reading a saved park's land and objects

Timeboxed investigation for [#78](https://github.com/joshgarlitos/generide/issues/78), unit U7. Question: can a plugin running in the headless game read the land and objects of a saved park, so a region of it can become a site that a ride is designed to fit?

**Status: not run yet.** The probe (`tools/park_probe.js`) is written and its output format is checked against a stand-in map, but it has not been run against the real game. Every finding below is blank until the owner runs it on a machine with the game and a saved park, and pastes the output under "Raw output". Nothing in `rct2/` depends on this spike, and the import unit (U8) waits on its decision.

## How to run it

Same route as the headless oracle spike (`docs/headless-oracle-spike.md`): load the park headless with no subcommand, and let a plugin print what it reads.

1. Open `tools/park_probe.js` and set `REGION` to a rectangle of your park, in map tiles as the game's tile inspector shows them. A 12 by 12 region with a few trees, a path and a bit of slope in it is ideal.
2. Copy the probe into the game's plugin folder, run the game on a saved park, and keep the result lines:

   ```bash
   cp tools/park_probe.js ~/Library/Application\ Support/OpenRCT2/plugin/
   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" <your-park>.park --headless \
       | grep '^GENERIDE_' > park-probe-output.txt
   rm ~/Library/Application\ Support/OpenRCT2/plugin/park_probe.js
   ```

3. Stop the game with Ctrl-C once `GENERIDE_DONE` appears (a plugin cannot quit the game).
4. Paste the output under "Raw output", fill in the findings, and state the game version.

The plugin has to live in the game's one real plugin folder, so remove it afterwards, exactly as with the oracle probe.

## What to find out

For each row, write yes, no or partial, and the evidence (a line from the output).

| Question | Finding | Evidence |
|---|---|---|
| Is the map size readable (`GENERIDE_MAP`)? | not run | |
| Does each tile report its surface height (`baseHeight` on `surface`)? | not run | |
| Does it report which land the player owns (`ownership` on `surface`)? | not run | |
| Does it report water (`waterHeight` on `surface`)? | not run | |
| Are footpaths visible (`footpath` elements)? | not run | |
| Is scenery visible, small and large (`small_scenery`, `large_scenery`)? | not run | |
| Are other rides' track and entrances visible (`track`, `entrance`)? | not run | |
| Is the surface slope reported, so a sloped tile can be told from a flat one (`slope`)? | not run | |
| Does the same read work with the park loaded headless and nothing on screen? | not run | |

## Units and coordinates

Fill in from the output:

- **Height units.** How much one step of `baseHeight` is, compared with the height unit generide's tracks use (`rct2/segments.py`, where a gentle slope rises 2 per tile). The import converts ground height into track units, so this has to be exact.
- **Coordinate origin.** Which corner of the map is tile 0, 0, and which way x and y grow, compared with generide's x (to the right of the ride) and y (ahead of it) in `rct2/site.py`.
- **Map size.** The largest region an import would ever need to read.

## Placing a design in the game

This part cannot be read by a plugin. Install a generated ride (the web UI's install button), then place it in the game by hand and write down:

- Which tile of the design lands under the cursor when you place it: the first station piece, the middle, a corner?
- Whether the design can be rotated as you place it, and how, so "rotate to face east" in the result can be worded correctly.
- What the game does with a station on sloped ground: refuse it, flatten the land, or build it anyway.

## Raw output

Paste `park-probe-output.txt` here, or the part of it that backs up the findings. Keep a small real region: the import unit uses it as a fixture for its tests.

```text
(not run yet)
```

## Decision

Pick one when the table above is filled in:

- **Build the import (U8).** The land, ownership and objects are readable, the units are known, and the ride can be placed and rotated as the result says.
- **Stay with the painted grid.** The map cannot be read headless, or too much of it is missing to tell a free tile from a blocked one. The painter (U5) becomes the lead input and the owner is asked what comes next.

**Decision: pending.** Game version and date of the run: pending.
