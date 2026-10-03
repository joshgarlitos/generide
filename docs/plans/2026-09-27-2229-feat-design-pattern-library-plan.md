---
title: Coaster Design Pattern Library - Plan
type: feat
date: 2026-09-27
topic: design-pattern-library
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Coaster Design Pattern Library - Plan

## Goal Capsule

- **Objective:** generide's part-based genome can draw on a growing library of known-good Mine Train design patterns, sourced from hand knowledge, the shipped-design corpus, and the project's own evolution runs, so that later work can make evolution converge on higher scores faster.
- **Means:** a human-gated pipeline. Two new tools (a corpus walker and a run-history miner) surface candidate patterns; a human promotes a candidate to a real genome part; nothing is written into the genome automatically.
- **Product authority:** the user (Josh) decides scope and promotion; this plan does not delegate either.
- **Open blockers:** the validation spike (R1-R3) has not run yet. Everything past it is contingent on what the spike finds.

---

## Product Contract

### Summary

Add a human-gated pattern library to generide: a corpus-extraction tool and a run-history mining tool that each surface candidate Mine Train design patterns, which a human reviews and promotes into the part-based genome one at a time. Before building either tool, a one-off validation spike checks whether the available data (the shipped-design corpus and existing run history) actually contains recognizable structure worth mining.

### Problem Frame

The part-based genome (`rct2/mutations.py`) has exactly one hand-defined structural element today: a mandatory lift hill at a fixed index. Everything else mutation can place is a generic slope run, banked run, or single segment chosen at random — there is no vocabulary of named higher-level elements (a drop, a turnaround, a split lift with a turn) despite that being the stated direction in `docs/research-plan.md:299-303`. Making the lift hill mandatory rather than left to chance already took the benchmark median from 1.87 to 4.33 (`docs/research-plan.md:306-308`); the open question this plan addresses is whether more hand-known and mined patterns can push that further, without trusting a corpus too small to draw firm conclusions from unsupervised.

### Requirements

**Validation spike**

- R1. A one-off script mines the locally available shipped Mine Train designs (the roughly 7 fully parseable ones referenced in `docs/research-plan.md:307-308`) for repeated part-like subsequences and reports what it finds, with no genome or pipeline integration.
- R2. The same pass diffs successive best-track structures recorded in at least one completed run's `improvements.jsonl` across its fitness jumps, using existing data with no new instrumentation, to check whether the jumps correspond to recognizable structural changes.
- R3. The user reviews R1 and R2's output and decides whether it shows enough real structure to justify the rest of this plan before any further requirement starts.

**Per-mutation instrumentation**

- R4. The run library records one entry per mutation event (a reference to the parent structure, the mutation type applied, and the resulting fitness delta), in addition to the existing per-generation (`progress.jsonl`) and per-improvement (`improvements.jsonl`) logs, for every evolution run from this point forward.
- R5. The existing per-generation and per-improvement log shapes stay unchanged; the per-mutation log (R4) is additive.

**Extraction tooling**

- R6. A corpus-extraction tool accepts a local directory of `.td6` Mine Train designs and outputs candidate structural patterns (part-like segment sequences with entry and exit height and direction), separate from `rct2/calibration.py`'s existing scalar-rating extraction, which does not touch track structure.
- R7. A run-history mining tool reads the per-mutation log (R4) across one or more completed runs and outputs candidate patterns whose presence correlates with large fitness deltas.
- R8. Both tools output candidates in one shared format, so a human reviewing them sees hand-authored, corpus-derived, and run-derived candidates side by side.

**Human-gated promotion**

- R9. A candidate pattern becomes a new part in the genome only once a human explicitly promotes it. No tool output writes into the part library directly.
- R10. A promoted pattern must pass the game's own placement legality check before mutation may place it — the same bar the two existing hand-defined parts (station, lift hill) already meet, using the query-the-game approach `docs/research-plan.md:112-147` describes rather than a hand-transcribed rulebook.
- R11. Every promoted pattern stays within the Mine Train ride type; no pattern derived from another ride type's shipped design is promoted.

### Key Decisions

- **Human-gated promotion over full automation** (session-settled: user-directed — chosen over an automatic pipeline that writes candidates straight into the genome: the shipped-design corpus and the project's own run history are both still too small to trust unsupervised). Governs R9, R10, R11.
- **Per-mutation logging added now, not deferred** (session-settled: user-directed — chosen over mining the coarser existing generation/improvement snapshots: mining precision depends on knowing which specific move produced a jump). Governs R4, R5, R7.
- **Parts come first; mutation-bias use of the same mined data is future direction, not active scope** (session-settled: user-directed). See Scope Boundaries.
- **Mine Train only** (session-settled: user-directed — chosen over pulling patterns from any ride type whose pieces are legal for a Mine Train, to stay consistent with the boundary `STRATEGY.md` already states). Governs R11.
- **The validation spike gates the rest of the plan** (session-settled: user-approved). Governs R1, R2, R3.

### Key Flows

- F1. Candidate pattern to promoted part
  - **Trigger:** a candidate pattern is produced, by hand-authoring, by the corpus-extraction tool (R6), or by the run-history miner (R7).
  - **Steps:** the human reviews the candidate; the candidate is checked against the game's placement legality rules (R10); on a pass and an explicit promote decision (R9), the pattern is added as a new part definition the parts genome can place, the same way today's hand-defined slope-run and bank-run builders are.
  - **Outcome:** the promoted pattern becomes one of the options `mutate_parts`/`crossover_parts` can choose, without changing anything about how already-promoted parts behave.
  - **Covers:** R6, R7, R9, R10.

### Acceptance Examples

- AE1. **Given** the validation spike (R1, R2) finds no recognizable structure in either the shipped-design corpus or the run history, **when** the user reviews the findings (R3), **then** the remaining requirements (R4-R11) do not proceed and the effort stops at the spike. Covers R3.
- AE2. **Given** a candidate pattern passes the game's placement legality check (R10) and the user promotes it (R9), **when** the parts genome mutates, **then** the promoted pattern is available as one of the choices mutation can pick, alongside the existing slope-run and bank-run builders. Covers R9, R10.
- AE3. **Given** a candidate pattern fails the game's placement legality check (R10), **when** the human attempts to promote it, **then** promotion is rejected and the pattern never enters the part library. Covers R9, R10.

### Success Criteria

- Re-running the existing `ga_parts` benchmark protocol from `docs/research-plan.md` (25 seeds, equal evaluation budget, the same rung already used for the 4.33 median baseline) with at least one promoted pattern-derived part added to the vocabulary shows a higher median score on the ported ratings model than that 4.33 baseline.

### Scope Boundaries

- No ride types beyond Mine Train (R11).
- No automatic or ungated promotion into the genome — every promotion is a human decision (R9).
- No requirement that the real-game oracle (`rct2/oracle.py`) confirm the improvement. The bar for this plan is the ported-model benchmark median; oracle confirmation follows the project's existing separate measurement track.

Deferred for later, once the human-gated pipeline is proven reliable:

- Loosening the promotion gate toward automatic promotion.
- Extending the same mined pattern data into mutation bias or search guidance, so evolution converges on a good score faster rather than only having a larger vocabulary to build from.

### Dependencies / Assumptions

- Assumes local access to the shipped `.td6` Mine Train designs (the roughly 7 fully parseable ones, and optionally the broader corpus `rct2/calibration.py` already draws scalar stats from) outside this repo, the same access pattern `extract_calibration_data.py:22` already uses (a directory argument, searched recursively).
- Assumes at least one completed evolution run with an `improvements.jsonl` exists, or will be run, to feed the R2 spike.

### Outstanding Questions

**Resolve Before Planning**

- Does the validation spike (R1-R2) find real, recognizable structure in either source? R4 through R11 are contingent on a yes; a no ends this plan at the spike per AE1.

**Deferred to Planning**

- The exact candidate-pattern representation (fields, serialization) shared by R6, R7, and R8.
- Where the per-mutation log (R4) lives and its on-disk shape.

### Sources / Research

- `docs/research-plan.md:299-303`, `:306-308`, `:357-359` — the parts-based genome direction, the 2026-08-15 benchmark result, and the open question about whether the 7 parseable designs are enough to extract a vocabulary from.
- `docs/research-plan.md:112-147` — the game-as-source-of-truth approach for placement legality (Tier 1), which R10 reuses.
- `rct2/mutations.py:592-856` — the current part-based genome: `_group_runs`, `segments_to_parts`, the fixed station/lift-hill indices, `mutate_parts`, `crossover_parts`, and the `builder(rng, current_z)` extension point a new pattern would plug into.
- `rct2/runrecord.py` — the run library's current per-generation (`progress.jsonl`) and per-improvement (`improvements.jsonl`) logs, and the absence of a per-mutation-event log, which R4 adds.
- `rct2/calibration.py`, `extract_calibration_data.py` — the existing scalar-stat extraction pattern and its directory-argument access to a local, uncommitted `.td6` corpus, which R6 follows for structure instead of scalars.
- `STRATEGY.md` — the "not supporting ride types beyond mine trains right now" boundary, which R11 keeps.
