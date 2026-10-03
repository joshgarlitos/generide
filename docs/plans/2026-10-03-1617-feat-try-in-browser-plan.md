---
title: Try generide in the Browser - Plan
type: feat
date: 2026-10-03
topic: try-in-browser
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Try generide in the Browser - Plan

## Goal Capsule

- **Objective:** A developer who finds generide through Josh's portfolio can pick ride settings, press go, and watch a Mine Train ride evolve, from a single link, without installing anything.
- **Means:** A public static page that runs generide's own evolution engine inside the visitor's browser, with no server behind it (approach A from the brainstorm).
- **Product authority:** This Product Contract is authoritative on behavior and scope. A smoother local install and a one-click cloud dev environment are related later areas, not active scope.
- **Open blockers:** None.

---

## Product Contract

### Summary

A public web page runs generide's evolution engine in the visitor's browser. The visitor chooses from a short set of ride settings sized so runs finish fast, presses go, and watches the plan, side profile, and best score improve live. The run ends with the finished ride, its stats, and a `.td6` download, and the page points to the repository for anyone who wants the full tool.

### Problem Frame

Josh links generide from a portfolio, and the people who follow that link are developers deciding in a few minutes whether the project is interesting. Today the only way to see generide do anything is to clone the repository, create a Python virtual environment, and start a local server. Most visitors stop before that point, so they never see the part that makes the project worth a look: a ride taking shape generation by generation.

Most of those visitors also don't own RollerCoaster Tycoon 2. OpenRCT2 needs the original game's data files, so the in-game half of generide (checking a ride in the headless game, installing it) is out of reach for them on any operating system. Whatever a visitor sees first has to stand on its own without the game.

### Key Decisions

- **Visitors are developers checking out the portfolio, not RCT2 players or contributors.** They give the project a few minutes and are comfortable with a browser, not necessarily with a terminal session. (session-settled: user-directed; chosen over other RCT2 players, Josh on a new machine, and a specific person: the trigger is someone browsing the portfolio wanting to try it out.) Governs R1, R11.
- **This work covers trying generide without installing it; a smoother install is a separate later piece.** (session-settled: user-directed; chosen over a smoother install first and over doing both together: the first impression decides whether a visitor ever installs.)
- **The visitor configures and starts a run; watching a recording is not enough.** (session-settled: user-directed; chosen over a GIF, video, or replay of a saved run: the visitor should be able to pick settings and press go.) Governs R3, R5.
- **The engine runs in the visitor's browser, with no server.** generide's engine uses only the Python standard library, which makes this feasible, and it leaves nothing to host, pay for, or protect from abuse. (session-settled: user-directed; chosen over hosting the existing web UI on a server, which needs per-visitor sessions, rate limits, and a running bill, and over an Open in Codespaces button, which needs a GitHub account and a boot wait.) Governs R2, R12.
- **Settings are a curated subset with limits that keep runs fast.** (session-settled: user-directed; chosen over the full local settings range and over named presets: a visitor who picks large settings would wait several minutes.) Governs R4, R6.
- **No run library on the page.** A run lasts until the visitor leaves or refreshes, and the `.td6` download is how they keep it. (session-settled: user-approved; proposed with the tradeoff shown: saving runs in the browser adds carrying cost a one-visit demo does not need.) Governs R9.
- **The page says plainly that game checks and installs need the local tool.** (session-settled: user-approved; proposed over hiding those features: a visitor who knows RCT2 would otherwise wonder where they went.) Governs R10.
- **The page tracks the main branch automatically.** (session-settled: user-approved; proposed over republishing by hand: an engine change that never reaches the page leaves the demo showing older behavior.) Governs R12.
- **Desktop browsers come first.** (session-settled: user-approved; proposed over designing for phones: portfolio visitors who try code are mostly at a computer.) Governs R13.

### Requirements

**Reaching the page**

- R1. A visitor reaches a working page from one link, with no account, sign-in, download, or install step.
- R2. The page runs generide's evolution engine in the visitor's browser; no generide server takes part in a run.
- R3. Before the first run, the page tells the visitor in one or two sentences what generide does and what pressing go will produce.

**Setting up a run**

- R4. The visitor chooses from a short set of settings that shape the ride, such as rating targets, station length, and seed, each with a plain explanation and its allowed range, using the wording the local web UI already uses where one exists.
- R5. The visitor can start a run with the defaults untouched, so one click is enough to see generide work.
- R6. Every combination of allowed settings finishes in roughly 30 seconds or less on a typical laptop in a current desktop browser, with run-size limits set by measurement in the browser; if measurement shows that time cannot meet R16, the time limit rises rather than the ride bar falling.
- R7. Settings mistakes are pointed out beside the field before the run starts, as in the local web UI.
- R16. With the default settings, the finished ride passes construction checks, its train finishes the circuit, and it has at least one real drop.

**Watching and finishing a run**

- R8. While a run is going, the page shows the generation, the best ride so far as a plan and a side profile, and the best score by generation, updating live, and once the first generation has appeared the visitor can stop the run and keep its best ride.
- R9. When a run ends, the page shows the finished ride's plan, side profile, and stats, labels generide's own estimates as estimates, flags a ride that fails construction checks or whose train does not finish the circuit, offers the ride as a `.td6` download, and lets the visitor return to the settings, with their last choices kept, to start another run.
- R10. The page states that checking a ride in the headless game and installing it into OpenRCT2 need the local tool, and links to the repository's instructions for it.
- R11. After a run, the page points the visitor to the repository and to running the full tool locally.

**Keeping the page healthy**

- R12. Publishing an engine change on the main branch updates the page without a manual step, and the page runs the same engine code as the repository, not a separate copy. Before a new version goes live, publishing runs the default and the largest allowed settings in a headless browser, and keeps the last good page live if either run fails or takes longer than R6 allows.
- R13. On a phone or an unsupported browser, the page either works or says plainly that it needs a desktop browser, rather than failing silently.
- R14. A visitor with a slow connection sees progress while the page loads, so the first wait never looks like a broken page.
- R15. If the engine fails to load or a run errors partway, the page shows a plain message, a way to retry, and the repository link, rather than a blank or frozen page.

### Key Flows

- F1. First visit to finished ride
  - **Trigger:** A visitor follows the link from the portfolio or the README.
  - **Steps:** The page loads and shows loading progress (R14), then a short explanation and the settings (R3, R4). The visitor presses go with the defaults or after changing settings (R5, R7). The ride evolves on screen (R8). The run ends with the result, the download, and a pointer to the repository (R9, R11).
  - **Outcome:** The visitor has watched a ride they configured come together and holds its `.td6`.
  - **Covered by:** R1 to R11, R14

### Acceptance Examples

- AE1. **Covers R5, R6, R8, R16.** Given a first-time visitor on a laptop, when they press go without changing any setting, then the first generation appears within a few seconds, the run finishes within R6's limit, and the ride has at least one real drop.
- AE2. **Covers R8.** Given a run in progress, when the visitor presses stop, then the run ends and the page shows the best ride found so far, the same as a finished run.
- AE3. **Covers R9.** Given a run whose best ride fails construction checks or whose train does not finish the circuit, when the run ends, then the result is flagged and the download is still offered with that flag visible.
- AE4. **Covers R10.** Given a visitor looking at a finished ride, when they look for a way to check it in the game or install it, then the page tells them those need the local tool and links to how to set it up.
- AE5. **Covers R13.** Given a visitor on a phone whose browser cannot run the engine, when they open the link, then they see a message that the page needs a desktop browser, plus the link to the repository.
- AE6. **Covers R9.** Given a finished run, when the visitor refreshes or leaves the page, then the run is gone; nothing on the page claims it was saved.
- AE7. **Covers R15.** Given a visitor whose browser fails to load the engine, when loading stops, then the page says the demo could not start, offers a retry, and links to the repository.

### Success Criteria

- A visitor with no prior setup goes from opening the link to a finished ride in about a minute, page load included, or in that time plus whatever R6's limit rises by.
- The ride the page produces for a given seed and settings matches what the local CLI produces when given the same seed and every setting the page used, including the fixed settings the page does not show.

### Scope Boundaries

- No headless-game checks or OpenRCT2 installs on the page (R10 covers how the page handles their absence).
- No run library, rerunning of saved runs, or side-by-side comparison on the page.
- No full settings range, benchmark harness, or other fitness methods beyond what the curated settings need.
- No server, accounts, or saved state shared between visitors.
- No layout designed for phones beyond R13.
- Deferred for later: a smoother local install for visitors who are hooked, and an Open in Codespaces button (see How This Work Fits Together).

<!-- ce-section: work-relationships -->
### How This Work Fits Together

This plan covers trying generide in the browser without installing it. The breakdown below is the current understanding, not a committed roadmap.

- Smoother local install: fewer steps from clone to a running web UI, and clear messaging that game features are optional and need RCT2.
  - Enables: R11's pointer to the repository lands on a shorter, friendlier path.
  - Can proceed independently of this plan.
- Open in Codespaces button: a ready cloud container that starts the full local web UI.
  - Shares the goal of a zero-install start with this plan, for developers willing to wait for a container.
  - Still to decide: whether it is part of the install work or its own piece.

### Dependencies / Assumptions

- generide's engine (`rct2/` and `evolve_coaster.py`) imports only the Python standard library, and `requirements.txt` lists only `pytest`. The in-browser approach depends on that staying true for the code paths a run uses.
- Evolution reads `data/sample_rides/manic_miner_test.td6` as its template, so the page has to ship that file.
- The plan, side profile, and score-by-generation pictures are drawn in Python as SVG (`rct2/render.py`), not in browser JavaScript, so the in-browser engine can produce the same pictures the local web UI shows.
- Assumption: Python running in a browser is slower than native Python by a factor small enough that R6's limits still allow rides that meet R16; if not, R6 says which side gives way. A 30-generation, population-30 physics run took about 15 seconds in native Python; the README's example run takes one to two minutes.

### Outstanding Questions

**Deferred to Planning**

- Which settings make the curated set, and what run-size limits meet R6 once measured in a browser.
- Where the page is hosted, and how R12's automatic update is wired.
- How a run is driven in the browser, given that the local web UI starts each run as a separate operating-system process (`rct2/webui.py`).
- How much of the local web UI's front end (`rct2/webui_static/`) the page reuses.

### Sources / Research

- `README.md` "Try it" and "Use the web UI" sections: the install steps and screens the page is measured against.
- `rct2/webui.py`: runs start through `subprocess.Popen`, and only one run is allowed at a time.
- `rct2/render.py`: `render_track`, `render_profile`, and `render_fitness_history` build the SVG pictures.
- `rct2/oracle.py` and `rct2/openrct2_paths.py`: macOS default paths for OpenRCT2, which explain why game features stay local.
- `STRATEGY.md`: names Josh as the primary user, with other players as an eventual secondary audience.
- `docs/plans/2026-09-27-0936-feat-web-ride-workbench-plan.md`: the local web UI this page borrows wording and views from.
