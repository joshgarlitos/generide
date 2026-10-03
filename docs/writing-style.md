# Writing style guide

This guide covers how generide's text reads: documentation, the README, the devlog, a future wiki, issues, pull requests, commit messages, and the words in the web UI. For how generide looks, see the [design system](design/README.md).

generide follows the [Google developer documentation style guide](https://developers.google.com/style). This page lists the parts of that guide that come up most often in this project, and the places where generide differs from it. When the two disagree, this page wins. For anything neither covers, use the Google guide, then [Merriam-Webster](https://www.merriam-webster.com/) for spelling.

## Audience

Write for two readers:

- **An RCT2 player** who knows the game well, can run a Python script, and wants a ride for their park. They know what excitement, intensity, and a chain lift are. They may not know what a genetic algorithm or a checksum is.
- **A contributor** who reads Python and wants to change generide. They need exact file names, function names, and numbers.

When a page is for only one of these readers, say which one in its first paragraph.

## Voice and tone

Write the way a knowledgeable colleague explains something at a whiteboard: direct, specific, and friendly, without jokes that get in the way of the facts.

- **Be precise.** Name the exact file, function, flag, number, and unit. "The run took 125 seconds for 100 generations" is better than "the run was a little slower."
- **Be natural.** Use short, common words and complete sentences. Read a sentence aloud; if you wouldn't say it that way, rewrite it.
- **Be honest about what's known.** Say what was measured and what was estimated. If something isn't explained yet, say so in one sentence and link to where it's tracked.
- **Lead with the point.** Put the answer, result, or instruction in the first sentence of a section. Put background after it.

## Person, voice, and tense

- **Address the reader as "you"** in guides, reference pages, the README's instructions, and UI text.
- **Don't use "we."** In documentation, name the actor: "generide checks the circuit," "the headless game rates the track," or "you run `pytest`."
- **Use active voice.** "The validator rejects the track" is better than "the track is rejected." Use passive voice only when the actor is unknown or doesn't matter.
- **Use present tense** for what generide does. "`evolve()` returns the best individual," not "`evolve()` will return."
- **Keep documentation timeless.** Don't write "currently," "now," "new," "soon," "at the moment," or "as of this writing" in guides and reference pages. Describe what is true. Put plans in `docs/roadmap.md` and history in the devlog.

The devlog is the exception to the first three rules. See [Devlog entries](#devlog-entries).

## Sentences and paragraphs

- **Put the condition before the instruction.** "To install a ride, click **Install**," not "Click **Install** to install a ride." The reader then knows whether the sentence applies before they act.
- **Put one idea in a sentence** and one topic in a paragraph. Keep most paragraphs under five sentences.
- **Use a noun, not "this" or "it," when the referent could be unclear.** "This change doubled the run time" is better than "this doubled it."
- **Define a term the first time you use it** on a page, or link to its entry in [`CONCEPTS.md`](../CONCEPTS.md).
- **Don't pre-announce.** Describe what exists. Don't describe features that aren't built as if they were.

## Words to avoid

| Avoid | Use instead | Why |
|---|---|---|
| simply, just, easy, obviously, of course | (delete) | What's easy for you may not be easy for the reader. |
| please | (delete) | Instructions don't need it. |
| e.g., i.e., etc., via | for example, that is, and so on, through | Latin abbreviations are easy to misread. |
| utilize, leverage, facilitate | use, help | Plain words say the same thing. |
| currently, now, new, soon | (delete, or give a date in the devlog) | Documentation should stay true without edits. |
| click here, this link | Link text that names the destination | Link text should make sense on its own. |
| real, actual, genuine (as intensifiers) | (delete) | Keep them only when the opposite is a live possibility, such as a real game versus generide's model of it. |
| a number of, various, several | the count | Give the number when you know it. |
| should (for generide's behaviour) | does, or "is expected to" with a reason | "Should" hides whether it works. |

## Precision rules for generide

These rules are specific to this project.

- **Separate estimates from game results.** Say "estimated excitement" for generide's own calculation and "game excitement" or "the game's rating" for numbers from OpenRCT2. Never report the two as one number.
- **Give the seed and settings** with any result someone might want to reproduce: "seed 4812, 30 by 30 footprint, 100 generations."
- **Give the unit with every measurement,** separated by a space: 22.0 m, 46 mph, 3.41 g, 30 tiles. Speeds use mph, the unit the web UI shows.
- **Use numerals** for every measurement, count that generide computes (pieces, generations, tiles, tests), version, and rating. Spell out zero through nine only in casual counts in prose ("two approaches").
- **Name code by its identifier** in code font: `physics.trace()`, `rct2/runrecord.py`, `--oracle-calibrate`.
- **Name ride types as the game does**, with capitals: Mine Train, Wooden Roller Coaster.
- **Link issues and pull requests with full URLs** in files in the repository, because `#63` only turns into a link inside GitHub issues and pull requests. For example: [issue 63](https://github.com/joshgarlitos/generide/issues/63).

## Formatting

### Headings

- Use sentence case: "Install a ride," not "Install A Ride."
- Start task headings with a verb in its base form: "Run the web UI," "Check a ride in the game."
- Use noun phrases for concept and reference headings: "Run records," "Fitness functions."
- Use one `#` heading per page, and don't skip levels.
- Don't end a heading with a period, and don't put code or links in a heading unless the heading names a file or function.

### Lists

- Introduce a list with a complete sentence that ends in a colon.
- Use a numbered list for steps in order, and a bulleted list for everything else.
- Keep list items parallel: all sentences, or all fragments, starting with the same part of speech.
- End every list item that is a complete sentence with a period.
- Use the serial comma in running text: "closure, collisions, and bounds."

### Procedures

1. Put one action in each step.
2. Start each step with a verb, or with the condition that applies to it.
3. Put commands the reader types in a code block right after the step.
4. Say what the reader sees when the step works, if it isn't obvious.

For example:

> 1. Start the web UI:
>
>    ```bash
>    python generide_web.py
>    ```
>
>    The terminal prints the address of the page.
>
> 2. Open that address in a browser.

### Code

- Use code font for file names, paths, commands, flags, function names, class names, variables, field names, and values the reader types.
- Declare the language on every fenced code block (`bash`, `python`, `text`).
- Don't include the shell prompt (`$`) in commands the reader copies.
- Write placeholders in capitals with underscores, such as `RUN_ID`, and explain each one after the block.
- Keep example output short and mark it as output with a `text` block.

### Links

- Make link text say where the link goes: "see the [research plan](research-plan.md)," not "see [here](research-plan.md)."
- Use relative links between files in the repository.
- Link a term once per section, the first time it appears.

### UI element names

- Put a UI element's name in bold, spelled exactly as it appears: **Start run**, **Check in game**.
- Use "click" for buttons and links, "select" for options, check boxes, and tabs, and "enter" for typed text.

### Tables and images

- Introduce every table and image with a sentence.
- Give every image alt text that says what it shows, and every chart a description of what it measures.
- Put units in column headers, not in every cell: "Top speed (mph)."

### Punctuation

- **Don't use em dashes.** This is where generide differs from the Google guide. Use a colon, a comma, parentheses, or a new sentence instead. Don't substitute an en dash for the same purpose, and write number ranges with "to": "10 to 60 tiles."
- Don't use exclamation marks.
- Use straight quotes and apostrophes in source files.
- Use American spelling in prose. Keep identifiers from other projects as they are spelled there, such as OpenRCT2's `colour`.

## Text in the web UI

The web UI's words follow this guide and the [design system](design/README.md). These rules cover the rest:

| Element | Rule | Example |
|---|---|---|
| Window title | A noun phrase naming the thing. | Run library |
| Tab | One or two words. | Ratings |
| Button | A verb and, if needed, its object. It says exactly what happens. | Check in game |
| Main action | The next step the reader takes in that window. | Start run |
| Stat | Label, colon, value, unit, optional qualifier, as the game writes them. | Max. vertical g: 3.41 g |
| Field hint | The unit and the allowed range, as a fragment. | Tiles, 10 to 60. |
| Error | What happened, then what to do. No apology and no blame. | OpenRCT2 didn't start. Set `GENERIDE_OPENRCT2_BINARY` to the game's path, then try again. |
| Prompt | Name the thing being changed, and say whether it can be undone. | Delete "Steep drops, seed 9" and its saved tracks? You can't undo this. |
| Ticker message | One event, in past tense or as a label with its figures. | New best ride in Mine Train 1: excitement 5.27, 98 pieces. |
| Empty state | What will appear, then how to add the first one. | Runs you start appear here. Click **New run** to start one. |

## Document types

Match the page to one of these types, and don't mix them on one page.

| Type | Where | What it does | Opens with |
|---|---|---|---|
| README | `README.md` | Says what generide is, what works, and how to try it. | One sentence on what generide does. |
| Guide | `docs/` or the wiki | Walks through one task in numbered steps. | What the reader will have done at the end, then "Before you begin." |
| Concept | `docs/` or the wiki | Explains how a part of generide works and why. | A one-paragraph summary. |
| Reference | `docs/`, `CONCEPTS.md` | Lists facts to look up: settings, fields, formats. | What the page lists. |
| Devlog entry | `docs/devlog.md` | Records what happened, what was learned, and what's next. | The date and title, then the result. |
| Solution write-up | `docs/solutions/` | Records one problem, its cause, and its fix, so the next person can find it. | The symptom. |
| Plan | `docs/plans/` | Describes work before it starts. | The goal and what done looks like. |
| Issue | GitHub | Describes one problem or request. | What happens, then what you expected. |
| Pull request | GitHub | Says what changed, why, and how it was tested. | A one-sentence summary. |

### Devlog entries

The devlog is Josh's first-person record, so it differs from the rest of the documentation:

- Write in first person ("I") and past tense for what happened.
- Head each entry `## YYYY-MM-DD: Title`, with a colon.
- Start with what changed or what was found, in one or two sentences. Then give the details in the order they happened.
- Keep the precision rules: numbers, units, seeds, file names, and links to the pull request or issue.
- End with the plain outcome, or with what's still to do.

### Commit messages

- Follow the existing convention: `type(scope): summary`, such as `fix(render): paint a background the dark theme can recolor`.
- Write the summary in lowercase, in the imperative ("add," not "added"), with no period, in 72 characters or fewer.
- In the body, say why the change was made and anything a reviewer can't see in the diff.

## Examples

These rewrites show the rules applied.

**Before:** "We've added a cool new way to simply check your ride in the game!"
**After:** "To see the game's own ratings for a ride, click **Check in game**. generide builds the track in a headless copy of OpenRCT2 and reads back its excitement, intensity, and nausea."

**Before:** "The fitness function currently rewards various properties, e.g. length, elevation, etc."
**After:** "The proxy fitness function rewards four properties: length, elevation change, turn balance, and piece variety."

**Before:** "The run was quite a bit slower after the change."
**After:** "After the change, 100 generations with physics scoring took 125 seconds instead of 124, at the same seed."

## Checklist

Check a page against this list before you merge it:

- [ ] The first sentence says what the page or section is for, or gives the answer.
- [ ] The reader is "you," the voice is active, and the tense is present (except in the devlog).
- [ ] No "currently," "new," "soon," "simply," "please," or Latin abbreviations.
- [ ] No em dashes and no exclamation marks.
- [ ] Every number has a unit, and every result that could be reproduced has its seed and settings.
- [ ] Estimates and game results are labelled separately.
- [ ] Headings are in sentence case, and task headings start with a verb.
- [ ] Steps are numbered, with one action each.
- [ ] Code, files, and flags are in code font; UI element names are in bold.
- [ ] Link text names its destination.
