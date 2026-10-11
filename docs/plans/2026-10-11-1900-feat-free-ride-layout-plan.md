---
title: Free Ride Layout Search - Plan
type: feat
date: 2026-10-11
topic: free-ride-layout
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Free Ride Layout Search - Plan

## Goal Capsule

- **Objective:** On a tight site, the generator finds rides that fit the space instead of breaking out of it, because it can build the layouts a human builder would try, such as a turn before the lift hill.
- **Means:** The lift hill stays a required part of every ride but may sit anywhere after the station, and the rules that fixed its place become score penalties wherever the game does not enforce them (see Key Decisions).
- **Authority:** Product Contract requirements win on behavior. Key Decisions record who chose what and why. Planning decides mechanism.
- **Open blockers:** None for planning. The train-length check (R10) must finish before any physics work on train length or the push out of the station.
- **Execution profile:** `ce-work`, measured on the site benchmark and the no-site benchmark before and after. The change touches the part-based search only, so the piece-based search and the exported ride file format are untouched.

---

## Product Contract

### Summary

The part-based search keeps one lift hill in every ride but stops pinning it to the slot right after the station. The lift rule is worked out from the finished track, and only what the game itself enforces stays a hard rule, so odd layouts can survive long enough to improve. A run returns the best playable ride and the best ride that fits the site, even if its train stalls. A small check in the game decides whether train length can become part of the design.

### Problem Frame

Using the site feature on a 14 by 14 test site, the generator let the ride break out of the space. It never tried layouts like station, curve, short lift, curve. The cause is in how rides are built: the part-based genome pins the station at part 0 and one lift hill at part 1, and mutation and crossover only work from part 2 on, so nothing can ever sit between the station and the hill (`rct2/mutations.py`, `HILL_INDEX`, `FIRST_FREE_INDEX`). The hill is a straight climb and drop of at least 10 tiles, so the station plus the smallest hill is one straight run 16 tiles long. No ride with the hill right after the station fits a space 14 tiles across in any heading.

This is a shortcut in the search, not a rule of the game. A hand-built `station, turn, hill` track passes generide's construction and physics checks, and the train completes with the lift landing on the hill. The pin was also earned: making the hill a mandatory part took median excitement from 1.87 to 4.33 and the share of runs clearing the drop-height threshold from 3 of 25 to 25 of 25 (`docs/research-plan.md`). A crude experiment that only freed the hill's position raised the blocked-centre site's fit rate from 40% to 100% on 5 seeds, but halved no-site median excitement from 4.24 to 2.14. The fix has to keep the hill mandatory and protect ride quality.

### Key Decisions

- **Free layout over footprint-first search, site seeding, and diversity search** (session-settled: user-directed, chosen over a footprint-first search, seeding from hand-made site layouts, and keeping odd layouts alive: closest to today's method and measurable on the existing site benchmark). Governs R1, R2, R3, R4.
- **Only game-enforced rules stay hard** (session-settled: user-directed, chosen over keeping every validity check hard, or checking only finished rides: lets odd layouts survive as stepping stones; the finished ride is still checked). Governs R5, R6.
- **A run returns both the best playable ride and the best fitting ride** (session-settled: user-directed, chosen over never returning a stalled ride and over returning only one). Governs R7.
- **Check train length in the game before deciding its role** (session-settled: user-directed, chosen over making it a search variable, a user setting, or leaving it out). Governs R10.
- **Keep one mandatory hill, free its position, and guard no-site quality** (session-settled: user-approved, proposed after an independent review found the free hill halves no-site quality; the user confirmed the revised scope). Governs R2, R8.

### Requirements

**Layout freedom**

- R1. The search can place a turn or other pieces between the station and the lift hill; the station stays first on the track.
- R2. Every ride the search builds has exactly one lift hill that clears the game's drop-height threshold, wherever it sits after the station.
- R3. The chain lift goes where the game would put it, on the first uphill run of the finished track, so a climb ahead of the hill that would take the lift away from it is scored as a failure to power the hill and is never accepted silently.
- R4. Each run's starting population includes layouts with the hill in different places, including after a turn, produced by the search's own moves and not by hand-made starting layouts.

**Rules and scoring**

- R5. A ride must be buildable in the game and be a closed circuit; every other failure, including a stalled train and a missing qualifying drop, is a score penalty and not a rejection.
- R6. Penalties are capped against the most a ride can earn, so they steer the search without making an invalid ride worth more than a valid one (`docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md`).
- R7. A run returns two rides: the best playable ride, and the best ride that fits the site even if its train stalls. The result shows both, labels the second as not playable when its train stalls, and shows one when they are the same ride.

**Measurement and the game check**

- R8. With no site, median excitement on the standard benchmark does not fall below today's level.
- R9. On the site benchmark, the blocked-centre site's fit rate rises above today's 40%, and the L-shape and downhill sites stay at today's 100%.
- R10. Before any physics change for train length or the push out of the station, a check establishes whether train length can be set in the ride file and in the headless oracle, and whether it changes how far the train rolls out of the station. Its result decides whether train length becomes a design variable, a user setting, or stays out.

### Success Criteria

- The first check Josh would make is that small sites fit: R9 is met with the 25-seed, 2,000-evaluation protocol the earlier benchmark used, not only 5 seeds.
- Ride quality holds: R8 is met on the same protocol.
- A tight site that no pinned layout can hold, such as a 14 by 14 site, reports its fit rate but is not a pass bar. Whether any closed loop with a hill fits it is not established.

### Acceptance Examples

- AE1. **Covers R1, R3.** Given a ride with a turn between the station and the hill, when it is scored, the chain lift lands on the hill, the train completes, and the ride counts as playable.
- AE2. **Covers R3, R5.** Given a ride with a small climb before the hill that takes the chain lift, when it is scored, the hill is reported as unpowered and the ride carries a penalty, but the search can keep it as a stepping stone.
- AE3. **Covers R7.** Given a run whose best fitting ride stalls, when the run finishes, the result shows the best playable ride and the fitting ride, and labels the fitting ride as not playable.
- AE4. **Covers R8.** Given a run with no site, when the benchmark runs before and after the change, median excitement is no lower than before.

### Scope Boundaries

**Deferred for later**

- A footprint-first search that finds a ground plan before placing lifts and drops.
- Seeding runs from hand-made compact site layouts.
- A search that keeps the best ride of each layout family alive.
- A turn inside the lift hill, and more than one chain-lifted climb.
- The rule that stops the search from dipping below its start level, which blocks sites whose ground falls away; it is a separate fix.
- Station flatness, the path to the entrance, and clearance above ground in the fit check.
- Ride types other than the mine train.

### How This Work Fits Together

<!-- ce-section: work-relationships -->

This plan covers freeing the lift hill's position and the train-length check. The broader breakdown below is the current understanding, not a committed roadmap.

- Train and station physics, if the check shows train length matters
  - Depends on the train-length check in R10.
- Seeding runs from compact site-fitting layouts
  - Enables better fit on very tight sites; depends on this plan's measurements to know if it is needed.
- Footprint-first search and keeping odd layouts alive
  - Can proceed independently of this plan and sit closest to the boundary in `STRATEGY.md` about new generation methods.
- Letting the search dip below its start level
  - Can proceed independently of this plan.
- Painting a site and importing one from a saved park
  - Can proceed independently; both create the sites this plan is measured on.

### Dependencies and Assumptions

- This changes the part-based search (`ga_parts`) only.
- "Fits" means the same tile check the site feature uses today (`rct2/site.py`).
- The headless oracle cannot set train length today (`ridesetvehicle` rejects every argument shape tried, `docs/devlog.md`), so R10 may end with "cannot be set yet".
- OpenRCT2's station departure speed was not established from source; the physics model's 2.2 m/s station push (`rct2/physics.py`) is the repo's own assumption.

### Outstanding Questions

**Deferred to Planning**

- What bar to set for R9 and R8 once the 25-seed baseline is measured, and how many seeds and evaluations to use.
- How the lift rule is worked out and applied during search and in the exported ride, given the game gives the lift to the first uphill run.
- How crossover keeps exactly one hill when the hill's position varies.
- How the starting population gets varied hill positions without hand-made layouts (R4).
- Whether any closed loop with a hill fits a 14 by 14 site, so it can be judged as a fair test.
- How the existing no-site seed and the exported ride stay the same when the hill does not move.

### Sources and Research

- `rct2/mutations.py`: `HILL_INDEX`, `FIRST_FREE_INDEX`, `ensure_hill_parts`, `mutate_parts`, `crossover_parts`, `repair_circuit`, and the `_stays_above_ground` check.
- `rct2/construction.py`: `build_hill`, `find_first_hill`, `default_lift_indices`, `MIN_HILL_HEIGHT`.
- `rct2/benchmark.py`: `canned_sites` and `run_site_benchmark`, the first fit rates in `docs/devlog.md` (2026-10-10).
- `docs/research-plan.md`: the measured effect of the mandatory hill.
- `docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md`: why penalties must be capped.
- `docs/plans/2026-10-09-0326-feat-site-aware-ride-fit-plan.md`: the site feature this builds on.
- A scratch experiment run for this brainstorm (hill free to move, 5 seeds, 800 evaluations): blocked-centre fit 40% to 100%, open 18 by 18 fit 0% to 20% with none usable, 14 by 14 fit 0% before and after, no-site median excitement 4.24 to 2.14. It was not committed and did not fix the lift rule, so treat it as directional.
