# Spike: headless OpenRCT2 as the ratings oracle

Timeboxed investigation for [#6](https://github.com/joshgarlitos/generide/issues/6). Question: can we place a track, run the game's own test lap, and read excitement/intensity/nausea back programmatically — without automating the UI?

**Verdict: GO.** Every link in the chain works. Measured cost is roughly **4 seconds per evaluation**, dominated by the test lap, against ~0.15s of fixed startup. That is too slow to score every individual in a GA run and entirely fine for scoring elites, which is exactly the hybrid the roadmap already describes.

Run on OpenRCT2 v0.5.3 (macOS AArch64), plugin API version 115, against the local RCT Classic install.

## The mode that works, and the two that don't

This was the least obvious part of the spike, so it comes first.

| Invocation | Plugins load? | Game advances? | Verdict |
|---|---|---|---|
| `openrct2 simulate <park> <ticks>` | No | Yes, ~30x realtime | Unusable — no way to read ratings |
| `openrct2 host <park> --headless` | Yes | **No** | Unusable — game state is immutable |
| `openrct2 <park> --headless` | Yes | Yes | **This one.** |

`simulate` looked ideal at first: it sets `gOpenRCT2Headless`, loads a park, and runs ticks in a tight loop, doing 500 ticks in 0.4s. But reading its source (`command_line/SimulateCommands.cpp`) shows it calls `gameStateUpdateLogic()` directly and never starts the scripting engine. A probe plugin in the plugin folder produced no output at all under it. It can advance a park quickly and tell you nothing about the result.

`host --headless` is the invocation the game's own `--help` suggests for headless use, and it does load plugins. But it puts the game in network mode, where the park loads paused and `context.paused = false` throws:

```
Error: Game state is not mutable in this context.
```

`interval.tick` never fires. The park sits frozen forever. `pause_server_if_no_clients` is already `false`, so this is not that.

Plain `openrct2 <park> --headless` — no subcommand — loads plugins, starts paused, and lets a plugin unpause itself. That is the one to build on.

## Measured numbers

**Startup to plugin running: 0.13–0.16s** across trials, including reading ratings for all 19 rides in the park. This cost is amortizable: one process can evaluate many candidates in sequence, so it is paid once per batch, not once per track.

**Tick rate by game speed**, measured over 4-second windows with `gamesetspeed`:

| speed | ticks/sec | vs. realtime |
|---|---|---|
| 1 | 40.7 | 1x |
| 2 | 79.7 | 2x |
| 4 | 318.3 | **8x** |
| 8 | rejected (`error=1`), stays at 318 | — |

Speed 4 ("hyper") is the ceiling. The game refuses higher values rather than clamping silently.

**Cost per evaluation.** A test lap costs the ride's own duration in game time. Our own generated rides run ~30 in-game seconds, so at 8x that is **~3.8s wall clock**, plus track construction and the fixed startup. Call it 4 seconds, and treat it as proportional to ride length rather than a constant.

At that price, scoring every individual is out: a 50x100 run is 5,000 evaluations, about 5.5 hours. Scoring the top 10 candidates of a run costs 40 seconds. The hybrid split the roadmap already calls for is not a compromise here, it is the only thing the measurement supports.

## The chain, link by link

Each of these was run and returned success in headless:

1. **Load the ride object.** Parks only carry objects they use, and Forest Frontiers has no Mine Train among its 42 ride objects. `objectManager.load('rct1.ride.mine_trains')` pulls it in at runtime and reports `rideType 17`, which is Mine Train. There are 2,518 installed objects available to load from.
2. **Create the ride.** `executeAction('ridecreate', {rideType: 17, rideObject: <index>, entranceObject: 0, colour1: 0, colour2: 0, inspectionInterval: 0})` → `error=0`, returns a ride id. The park gains "Mine Train Coaster 1".
3. **Place track.** `executeAction('trackplace', {...})` → `error=0`.
4. **Read ratings.** `map.getRide(id).excitement / .intensity / .nausea`, readable and plausible: a park's real rides came back at 657, 549, 787 and so on.

## Gotchas worth knowing before implementing

**Ratings use two different fixed-point scales.** The plugin API stores them x100 (`652` is 6.52, per the API docs). Our TD6 header parser uses `RATING_PER_UNIT = 0.1`, x10 — `manic_miner_test.td6` stores 62 for 6.2 excitement. Any code comparing oracle output against `td6.py` values has to convert. Getting this wrong produces a clean 10x error that will look like a modeling problem.

**An untested ride reads `-1`, not `0`.** Shops and unrated rides report `excitement = -1`. That is the signal for "no rating yet", and it needs distinguishing from a genuinely bad ride before feeding anything into fitness.

**Placing a `.td6` directly is not supported.** `executeAction('trackdesign', ...)` exists in the API surface but `TrackDesignArgs` is annotated `@todo Currently unsupported` and carries only a position, with no way to name which design. Tracks have to be built piece by piece with `trackplace`. For generide this is close to free — the genome already *is* an ordered segment list — but it does mean the oracle consumes a segment list, not a file.

**The plugin has to live in the real user plugin folder.** `--user-data-path` is a global option that the subcommands reject, and `OPENRCT2_USER_DATA_PATH` was ignored (the scratch directory was never touched). So an isolated plugin directory is not available; anything installed for a run is visible to the user's normal game and should be removed afterward.

**The published `.d.ts` is ahead of the installed build.** `RideCreateArgs` in the `develop` type definitions ends with `inspectionInterval`; passing `colour3` there instead — a plausible guess — fails with the unhelpful `Invalid action parameters`. Check argument shapes against the installed version, not the docs.

## Setup steps to reproduce

1. Confirm the binary and its RCT2 data path. `config.ini` must have `game_path` pointing at an RCT2 or RCT Classic install; ours is the Steam RCT Classic directory, and it works unmodified.

   ```bash
   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" --version
   ```

2. Put a plugin in `~/Library/Application Support/OpenRCT2/plugin/`. It must call `context.paused = false` in `main()` or nothing will ever tick.

3. Launch with no subcommand, capturing stdout:

   ```bash
   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" <park>.park --headless
   ```

4. Have the plugin `console.log` results behind a greppable prefix. The host process reads stdout line by line and kills the child once it sees the terminator — plugins have no file I/O and no way to quit the game, so stdout is the channel and the parent owns the lifecycle.

`tools/oracle_probe.js` is the working probe from this spike, kept as a starting point.

## What this spike did not prove

**No end-to-end rating of a known design.** The acceptance criteria asked for a sanity check against `data/sample_rides/`, and that did not happen. Each link works in isolation, but placing all 89 segments of `manic_miner_test.td6` and testing it is the implementation, not the spike, so the numbers here rest on the mechanism working rather than on a reproduced rating. The baseline to check against when someone does it, from the fixture's own header: **excitement 6.2, intensity 6.5, nausea 4.2**. If the oracle returns 620/650/420 for that segment list, it is validated.

**Nothing was measured about a test lap that fails.** Every timing here is from rides that already had ratings or from tick-rate probes. A track that stalls mid-circuit may never finish its test and never produce a rating, which means the oracle needs a timeout policy and a way to report "no rating" distinctly from a low one. Our `physics.simulate` already predicts stalls, so screening candidates before spending 4 seconds on them is likely the right shape.

**Determinism across runs is unverified.** If the same segment list can return different ratings on different runs, that matters for using the oracle as a fitness signal, and it was not tested.
