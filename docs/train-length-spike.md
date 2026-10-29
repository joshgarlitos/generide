# Spike: setting train length, and what it does to the roll-out

Timeboxed investigation for the free-layout plan (`docs/plans/2026-10-11-1900-feat-free-ride-layout-plan.md`), unit U2, requirement R10. Question: can the number of trains and cars per train be set in the ride file and in the headless game, and does a longer or shorter train change how far it rolls out of the station, so that it can reach a turn and then the lift hill?

**Status: not run yet.** The probe (`tools/train_probe.js`) is written and its output format is checked against a stand-in game object, but it has not been run against the real game. Every finding below is blank until the owner runs it on a machine with the game and pastes the output under "Raw output". Nothing in `rct2/` depends on this spike. Physics work on train length or the push out of the station waits on its decision.

## What is already known

- The headless oracle asks for a train setup with `ridesetvehicle`, and the game rejects every argument shape tried ("Invalid action parameters"), so the ride runs on the game's default of 3 trains and 12 cars in total (`docs/devlog.md`, 2026-08-23; the oracle prints the setup it read back as `GENERIDE_TRAINS`, parsed in `rct2/oracle.py`).
- The ride file format holds a train count and a cars-per-train count in its header (`num_trains`, `cars_per_train` in `rct2/td6.py`). Whether the game honours them when it loads a design was not tested.
- In generide's own physics a train is a point: train length is not modelled, and the station pushes the train at 2.2 m/s (`rct2/physics.py`). That number is the repo's assumption, not something read from the game.
- A sweep of `cars_per_train` from 1 to 6 in the ratings port moved excitement by only 0.14. That is the effect on the rating, not on how far the train rolls.
- OpenRCT2's station departure code was not reachable from source when this was planned, so how the game moves a train out of the station is not established.

## How to run it

1. Install a generated ride with the web UI, place it in the game, and save the park. Any finished mine train works, but it should have a station, a first lift and at least one turn.
2. Open `tools/train_probe.js` and check `RIDE_ID` (null picks the first ride in the park) and `CONFIGS`, the train settings to try. The first entry is the game's default and sets nothing.
3. Copy the probe into the game's plugin folder, run the game on the saved park, and keep the result lines:

   ```bash
   cp tools/train_probe.js ~/Library/Application\ Support/OpenRCT2/plugin/
   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" <your-park>.park --headless \
       | grep '^GENERIDE_' > train-probe-output.txt
   rm ~/Library/Application\ Support/OpenRCT2/plugin/train_probe.js
   ```

4. Stop the game with Ctrl-C once `GENERIDE_DONE` appears (a plugin cannot quit the game).
5. Optional, for the file route: write variants of the ride file with other train settings, place each in a park by hand, and run the probe on that park with only the first `CONFIGS` entry (this measures what the game built from the file):

   ```bash
   python3 - <<'EOF'
   import dataclasses
   from rct2 import td6
   ride = td6.load("data/sample_rides/manic_miner_test.td6")
   for trains, cars in [(1, 1), (1, 3), (1, 6)]:
       td6.save(dataclasses.replace(ride, num_trains=trains, cars_per_train=cars),
                f"train-{trains}x{cars}.td6")
   EOF
   ```

6. Paste the output under "Raw output", fill in the findings, and state the game version.

The plugin has to live in the game's one real plugin folder, so remove it afterwards, exactly as with the oracle probe.

## What the output holds

| Line | Meaning |
|---|---|
| `GENERIDE_RIDE_KEYS` | Every property the plugin API shows on the ride. A writable train-count property would appear here under whatever name it has. |
| `GENERIDE_TRAINS` | Cars and trains counted from the game's entities, before and after each attempt to set them. |
| `GENERIDE_ACTION` | The game's answer to each action: close the ride, each `ridesetvehicle` shape, reopen. |
| `GENERIDE_PROPERTY` | A direct write to the ride object, with the value before and after. |
| `GENERIDE_SAMPLE` | The lead car of each train every 25 ticks: position, speed, status and the track piece it is on. |

The `ridesetvehicle` shapes include one the oracle never sent: a `colour` field. That is a guess at why the oracle's calls fail, not a known cause, and the output says whether it was right.

## What to find out

For each row, write yes, no or partial, and the evidence (a line from the output).

| Question | Finding | Evidence |
|---|---|---|
| Does the game accept `ridesetvehicle` with the ride closed? | not run | |
| Does adding `colour` change the answer? | not run | |
| Does any direct property write change the train count (`GENERIDE_PROPERTY`)? | not run | |
| Does `GENERIDE_TRAINS` show the requested count after a setting that took? | not run | |
| Does a ride file with other `num_trains` and `cars_per_train` values load as asked? | not run | |
| With the default setup, how far does the lead car roll from the station, and does it reach the lift? | not run | |
| With a shorter train (1 car), how far does it roll? | not run | |
| With a longer train (6 cars), how far does it roll? | not run | |
| Does the roll-out distance change enough, between settings, to matter for a turn before the lift? | not run | |

## Raw output

Paste `train-probe-output.txt` here, or the part of it that backs up the findings.

```text
(not run yet)
```

## Decision

Pick one when the table above is filled in:

- **Train length becomes a design variable.** It can be set reliably and it changes the roll-out enough to decide whether a turn before the lift is possible. The physics model gains a train length and the search may vary it.
- **Train length becomes a user setting.** It can be set and it matters, but it is not something the search should choose. The user picks it and the physics and the exported file use it.
- **Leave it out.** It cannot be set in the headless game, or it does not change the roll-out enough to matter. The physics keeps treating the train as a point, and the station push stays an assumption.

**Decision: pending.** Game version and date of the run: pending.
