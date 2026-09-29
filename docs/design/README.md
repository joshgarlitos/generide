# generide design system

This document defines how generide looks: the web UI, a future devlog or wiki site, and the pictures and Markdown the project publishes on GitHub. The look is based on the in-game interface of RollerCoaster Tycoon 2 (RCT2). For how generide *reads*, see the [writing style guide](../writing-style.md).

The design system has three files:

- `docs/design/README.md` (this file) is the specification. When the other two files disagree with it, this file wins.
- [`docs/design/tokens.css`](tokens.css) is the reference implementation: colour tokens, spacing, type, and every component as CSS.
- [`docs/design/specimen.html`](specimen.html) shows each component dressed as a generide screen. Open it in a browser next to `tokens.css`.

generide is not affiliated with Atari, Chris Sawyer, or the OpenRCT2 project. The design borrows RCT2's visual rules, not its assets. See [Evoke the game, don't copy it](#evoke-the-game-dont-copy-it).

## How RCT2's interface works

Every rule in this document traces back to how the game draws its interface. The facts below come from OpenRCT2's source code, which reimplements RCT2's drawing routines and keeps the original's defaults.

### Windows have colour schemes

RCT2 gives every kind of window up to three colours from a fixed list of 32. The first colour paints the frame and title bar, the second paints the page under the tabs, and the third paints some controls. The colour tells you what kind of window you are looking at before you read it. These defaults come from `kWindowThemeDescriptors` in OpenRCT2's [`src/openrct2-ui/interface/Theme.cpp`](https://github.com/OpenRCT2/OpenRCT2/blob/develop/src/openrct2-ui/interface/Theme.cpp):

| Window | Colour 1 | Colour 2 | Colour 3 |
|---|---|---|---|
| Ride | grey | bordeaux red | saturated green |
| Ride list, scenario select | grey | bordeaux red | bordeaux red |
| Ride construction, track design place | dark brown | dark brown | dark brown |
| Track design list, install track | bordeaux red | bordeaux red | bordeaux red |
| Error, demolish ride, save prompt | bordeaux red (translucent) | | |
| Options | grey | light blue | light blue |
| Finances, research, park information | grey | dark yellow | dark yellow |
| Guest | grey | olive green | olive green |
| Staff | grey | light purple | light purple |
| Game status bar | dark green (translucent) | | |
| News ticker | black | black | |

### Each colour is a 12-step ramp

The game runs in an 8-bit, 256-colour palette. Each window colour maps to a ramp of 12 shades, from darkest to lightest. generide's ramps are the RGB values of the game's standard palette, taken from `StandardPalette` in OpenRCT2's [`src/openrct2/drawing/ImageImporter.h`](https://github.com/OpenRCT2/OpenRCT2/blob/develop/src/openrct2/drawing/ImageImporter.h). The file stores each colour as blue, green, red; `tokens.css` stores the same values as `#rrggbb`.

### Depth comes from one-pixel bevels

The game draws every box with `Rectangle::fillInset()` in OpenRCT2's [`src/openrct2/drawing/Rectangle.cpp`](https://github.com/OpenRCT2/OpenRCT2/blob/develop/src/openrct2/drawing/Rectangle.cpp). The function uses three shades from the box's ramp:

- The fill is the *light* shade.
- The highlight is the *lighter* shade.
- The shadow is the *mid-dark* shade.

A raised (outset) box has the highlight on its top and left edges and the shadow on its bottom and right edges. A sunken (inset) box swaps them. A button draws raised and switches to sunken while you press it. There are no gradients, rounded corners, or blurred shadows anywhere in the interface.

### Other conventions

- **Title bars.** The title bar is a sunken strip, darkened three palette steps below the window fill. The title text is white, centred, and drawn with a one-pixel black outline (`WidgetCaptionDraw()` in [`Widget.cpp`](https://github.com/OpenRCT2/OpenRCT2/blob/develop/src/openrct2-ui/interface/Widget.cpp)). The close button sits at the right end of the title bar.
- **Tabs.** Tabs sit along the top edge of the page. The selected tab joins the page below it.
- **Group boxes.** A group box is an etched frame, drawn as a mid-dark line with a lighter line one pixel below and right of it. Its label interrupts the top edge.
- **Lists.** Lists and text entry sit in sunken wells, lighter than the window. The selected row is filled with a darker shade.
- **Stats.** The ride window reports numbers as a label, a colon, and a value, sometimes followed by a qualifier: "Excitement rating: 6.52 (High)".
- **Ride graphs.** The ride window's graph tab plots speed, altitude, and g-forces over time as bright lines on a dark background with a grid.
- **Status bar and news ticker.** The bottom of the screen has a green status bar with the park's money, date, and guest count, and a black news ticker that shows one message at a time with an icon.
- **Text.** The game uses small bitmap fonts in black or white, with colour codes for emphasis (for example, yellow for highlighted names in news messages).

## Principles

### Everything lives in a window

Put every piece of content in a window. The page background is the "park": a textured field with nothing on it but windows, a toolbar at the top, and a status bar and news ticker at the bottom. Don't place text directly on the page background.

### Colour says what kind of window it is

Choose a window's colour by what the window is for, using the [window roles](#window-roles) table. Two windows of the same kind always have the same colours. Don't pick a colour because it looks good in one spot.

### Depth comes from bevels only

Use two-pixel bevels (one game pixel at the 2x scale OpenRCT2 uses for modern screens) for all depth. Never use `border-radius`, blurred `box-shadow`, gradients, or transparency on components.

### Evoke the game, don't copy it

RCT2's sprites, fonts, logo, and title screen are copyrighted, and "RollerCoaster Tycoon" is a trademark. Use the game's *rules* (palette values, bevel geometry, layout conventions) and draw every icon, sprite, and illustration from scratch. Don't extract images from the game's data files, don't ship a copy of its bitmap font, and don't use the RCT2 logo or name in a way that suggests the project is official.

### Readability beats fidelity

Where the game's choices would make the web UI hard to read or use, change them and write the change down here. The current deviations are:

- Text is 13 px Verdana instead of the game's 7 to 10 px bitmap font.
- Wells use a lighter step (10 or 11) than the game (8), so text inside them has a contrast ratio of at least 10:1.
- Text on bordeaux windows is white. Black text on the game's bordeaux fill measures 4.1:1, below the 4.5:1 minimum.
- Yellow and saturated green windows use a darker fill step than other colours, so black text passes.
- Focused controls show a yellow outline. The game has no keyboard focus.
- Controls grow from 28 px to 36 px tall on touch screens.

## Colour

### Ramps

`tokens.css` defines each ramp as `--<name>-0` (darkest) through `--<name>-11` (lightest). generide uses seven ramps, plus four steps of a grass ramp for the page background:

| Ramp | Palette indexes | Game colour it stands for | Fill (step 7) |
|---|---|---|---|
| `grey` | 10 to 21 | grey | `#839797` |
| `bordeaux` | 58 to 69 | bordeaux red | `#b34f4f` |
| `brown` | 214 to 225 | dark brown | `#a3937f` |
| `darkgreen` | 142 to 153 | dark green | `#639b77` |
| `lightblue` | 130 to 141 | light blue | `#5ba3e7` |
| `yellow` | 46 to 57 | dark yellow | `#d7a713` (step 6) |
| `green` | 94 to 105 | saturated green | `#379f17` (step 5) |
| `grass` | 70 to 81 | park lawn | `#577f33` (step 5) |

The exact shade offsets that the game uses for each window colour live in its data file (`g1.dat`), not in OpenRCT2's source. generide assumes each colour uses its ramp from step 0. Compare the web UI with a screenshot from OpenRCT2 before you change a ramp.

### Window roles

Each window colour class in `tokens.css` sets local variables that every component inside the window reads: `--fill`, `--hi` (highlight), `--lo` (shadow), `--deep` (title bar), `--well`, `--well-lo`, `--well-quiet`, `--ink`, `--hover`, and `--row-hover`. Put a class on a window and everything inside it follows.

| generide surface | Class | RCT2 counterpart | Why |
|---|---|---|---|
| New run request form | `c-brown` | Ride construction | You are building something. |
| Result of one run, with tabs | `c-grey` frame, `c-bordeaux` page | Ride window | It describes one ride. |
| Run library, compare view | `c-grey` frame, `c-bordeaux` page | Ride list | It lists rides. |
| Live run progress, status bar | `c-darkgreen` | Status bar, park panels | It reports what's happening now. |
| Numbers from the headless game | `c-yellow` | Finances, research | It shows figures that came from the game's own calculation. |
| Settings, help, reference pages | `c-lightblue` page in a `c-grey` frame | Options | It configures or explains generide. |
| Error and confirmation prompts | `c-bordeaux` | Error, demolish ride | It needs a decision before you continue. |
| The one main action in a window | `c-green` on the button | Ride window's third colour | It marks the button to press next. |
| Event messages | `.ticker` (black) | News ticker | It announces a change once. |

### Meaning is never colour alone

Every state that colour shows also appears as text. A game-checked number carries a yellow `GAME` badge, an estimate carries a dashed `estimate` badge, and a failed run says "Failed" in its status column. Keep generide's rule that estimates and game ratings are separate labels and are never merged.

### Light and dark schemes

Windows look the same in both schemes, as they do in the game. Only two tokens change:

| Token | Light | Dark |
|---|---|---|
| `--desktop` | `--grass-5` (lawn) | `--grey-0` (the game's black void) |
| `--desktop-tile` | `--grass-4` | `#0f1919` |

Because graphs sit in dark wells in both schemes, pictures drawn by `rct2/render.py` don't need a separate dark palette.

### Contrast

These pairs were measured with the WCAG 2 formula. Keep every text pair at 4.5:1 or higher. Recheck a pair when you change a step.

| Text | Background | Ratio |
|---|---|---|
| Black on grey fill | `#839797` | 6.8:1 |
| White on bordeaux fill | `#b34f4f` | 5.1:1 |
| Black on brown fill | `#a3937f` | 7.0:1 |
| Black on dark green fill | `#639b77` | 6.5:1 |
| Black on light blue fill | `#5ba3e7` | 7.8:1 |
| Black on yellow fill | `#d7a713` | 9.4:1 |
| Black on green fill | `#379f17` | 6.1:1 |
| White title text on grey title bar | `#3f5353` | 8.2:1 |
| White title text on yellow title bar | `#8f5307` | 6.2:1 |
| Quiet text in a grey well | `#3f5353` on `#d3dbdb` | 5.8:1 |
| Quiet text in a green well | `#176700` on `#c3ffb3` | 6.1:1 |
| Quiet text in a bordeaux well | `#6f0f0f` on `#ffbfbf` | 7.7:1 |
| Speed trace on graph background | `#ffe72f` on `#233333` | 10.5:1 |
| Chain lift trace on graph background | `#77bbef` on `#233333` | 6.4:1 |

Secondary text colours only pass contrast inside wells. On a window fill, all text uses `--ink`, and a hint is set apart by size, not colour.

## Type

| Role | Token | Face | Size |
|---|---|---|---|
| Window titles, brand | `--font-display` | Pixelify Sans, then Verdana | 13 px bold |
| Interface text | `--font-ui` | Verdana, Tahoma, DejaVu Sans | 13 px |
| Hints, table headers | `--font-ui` | same | 12 px |
| Long-form reading (devlog, wiki) | `--font-ui` | same | 15 px, line height 1.6 |
| Code, file names, commands | `--font-code` | DejaVu Sans Mono, Menlo, Consolas | 13 px |

Verdana stands in for the game's bitmap font. Both have wide, open letters designed to read at small sizes on screen. Pixelify Sans is an open-source (SIL Open Font License) pixel face that brings the bitmap feel to titles only. It is optional: the web UI runs offline, so ship the font file with the UI if you use it, and let Verdana take over when it's missing.

Rules:

- Use sentence case for window titles, tabs, buttons, and headings.
- Set numbers in columns with `font-variant-numeric: tabular-nums`.
- Write stats as the game does: label, colon, value, unit, then an optional qualifier in parentheses. For example, "Max. vertical g: 3.41 g".
- Don't use all caps, except for the `GAME` badge.
- Draw window titles white with a one-pixel black outline, as `.win-caption` does.

## Layout and spacing

- **One game pixel is `--u` (2 px).** Bevels are one `--u` wide.
- **Spacing steps are 4, 8, 12, 16, and 24 px** (`--space-1` to `--space-6`). Put space between siblings with `gap`, not margins.
- **Controls are 28 px tall** (14 game pixels, the height of an RCT2 button), and 36 px on touch screens.
- **Windows tile in a grid** that wraps to one column at phone width. They don't float or drag. A window's width comes from the grid, and its height comes from its content.
- **The toolbar is sticky at the top, and the status bar and news ticker are sticky at the bottom.** Toolbar buttons are grouped by the colour of the window they open, as they are in the game's top toolbar.
- **Density follows the game.** Windows are compact, with 12 px of padding. Use tabs to split a window with a lot of content, not longer pages.

## Components

Every component is in `tokens.css` and shown in `specimen.html`.

| Component | Class | Game behaviour it follows |
|---|---|---|
| Page background | `.desktop` | The park, or the black void in dark mode. |
| Window | `.win` + a colour class | Raised frame with a one-pixel black outline. |
| Title bar | `.win-caption` | Sunken, darker strip with centred, outlined white text. |
| Close button | `.btn.btn-icon.win-close` | Small raised button at the right end of the title bar. |
| Tabs | `.tabs`, `.tab[aria-selected]` | The selected tab drops two pixels to join the page. |
| Tab page | `.win-body.win-page` + a second colour class | The ride window's second colour. |
| Button | `.btn` | Raised. Sunken while pressed or when it's the current page. |
| Main action | `.btn.c-green` | One per window at most. |
| Text entry | `.input` | Sunken well. |
| Number entry | `.spinner` | Sunken well with down and up buttons on the right. |
| Drop-down list | `.select-wrap > .select` | Sunken well with a raised arrow button. |
| Checkbox | `.check` | Small sunken square with a tick. |
| Group box | `fieldset.groupbox` | Etched frame with the label in its top edge. |
| Stat list | `dl.stats > .stat` | "Label: value (qualifier)". |
| Well | `.well`, `.well-scroll` | Sunken, light area for lists, tables, and read-outs. |
| Graph well | `.well.well-graph` | Dark area for charts. |
| Table | `.table` in a `.well` | Column headers are raised buttons. The selected row is dark with white text. |
| Progress bar | `.progress > span` | Sunken track with a raised green fill. |
| Status bar | `.statusbar.c-darkgreen` | Bottom bar with live counts. |
| News ticker | `.ticker` | Black strip, one message, an icon on the left, names in yellow. |
| Prompt | `.win.c-bordeaux.prompt` | Centred text and buttons. |
| Game badge | `.from-game` | Yellow badge for numbers from the headless game. |
| Estimate badge | `.estimate` | Dashed outline for numbers generide calculated. |

### Behaviour

- **No hover animation.** A button gets a lighter fill on hover and sinks when pressed. Nothing slides or fades.
- **Prompts ask before destroying.** Delete, overwrite, and install actions open a bordeaux prompt that names the thing being changed and says whether you can undo it.
- **The news ticker reports events once.** Examples are a new best ride, a run that finished, and a game check that completed. It is a `role="status"` region, so screen readers announce it.
- **Motion is limited to progress.** The progress bar and the ticker may change. Everything else is still. Turn all motion off under `prefers-reduced-motion`.

## Charts and diagrams

generide's pictures (the plan, the side profile, the fitness curve, and the diagrams in `docs/assets/`) follow the game's ride graphs:

- Draw charts in a dark graph well: background `--graph-bg` (`#233333`), grid lines `--graph-grid` (`#3f5353`) at one pixel, and labels `--graph-axis` (`#b7c3c3`).
- Draw traces two pixels wide with square joins. Use one colour per quantity, and keep it the same on every chart:

  | Quantity | Token | Colour |
  |---|---|---|
  | Speed | `--trace-speed` | `#ffe72f` |
  | Height | `--trace-height` | `#afdbc3` |
  | Chain lift section | `--trace-lift` | `#77bbef` |
  | Stall point | `--trace-stall` | `#eb9f9f` |

- Shade the plan view by height with one ramp, from dark to light as the track climbs.
- Label every axis with its unit, and give every chart a text description (`<desc>` in SVG, `alt` on an image).
- Paint the background into the SVG. A chart with its own dark background reads the same on GitHub's light and dark themes, so it doesn't need CSS classes to recolour it.

## Icons and sprites

- Draw icons on a 12 or 16 pixel grid with hard edges, and scale them by whole numbers. Set `image-rendering: pixelated` on bitmaps.
- Colour icons with the palette ramps: a light edge on the top and left, a dark edge on the bottom and right, the same as a bevel.
- Every icon needs a text label next to it or an `aria-label`.

## Applying the system

### The web UI

The web UI (`rct2/webui_static/`) uses a flat, rounded style today. To move it to this system, copy `tokens.css` into `rct2/webui_static/`, wrap each view in windows, and map the current classes as follows:

| Current class | New component |
|---|---|
| `.topbar`, `nav a` | `header.c-grey` with `.toolbar`, `.toolgroup`, and `.btn[aria-current]` |
| `.brand` | `.brand` in the toolbar |
| `.active-chip`, `.pulse` | `.statusbar.c-darkgreen` item and a `.ticker` message |
| `.panel` | `.win` with a colour class and a `.win-caption` |
| `.banner.warn` | `.win.c-yellow` |
| `.banner.bad` | `.win.c-bordeaux.prompt` |
| `.banner.good` | `.ticker` message |
| `button`, `.button` | `.btn` |
| `button.primary` | `.btn.c-green` |
| `button.danger` | `.btn` that opens a bordeaux prompt |
| `.field input`, `.field select` | `.input`, `.spinner`, `.select-wrap > .select` |
| `details.advanced` | A second tab, or a `fieldset.groupbox` |
| `.metric`, `.live` | `dl.stats` in a `.win.c-darkgreen` |
| `.progressbar` | `.progress` |
| `.pictures img`, `img.chart` | `.well.well-graph` |
| `table`, `tr.changed` | `.table` in a `.well`, with `aria-selected` on changed rows |
| `.tag.game` | `.from-game` |
| `.tag.estimate` | `.estimate` |
| `.run-card` | A row in the run library `.table` |
| `.compare-bar` | `.statusbar` with the compare button |

Then update `rct2/render.py` to draw with the chart colours above.

### A devlog or wiki site

A future site (for example, one served by GitHub Pages) uses the same `tokens.css`:

- Each page is one window. The title bar holds the page title, and the body is a well at the long-form size (15 px, 68 characters wide).
- The site navigation is the toolbar. Group the links by colour: light blue for guides and reference, bordeaux for ride and run pages, brown for how-to pages about building a run.
- Devlog entries are windows in date order, newest first. Each entry's title bar holds its date and title.
- Code blocks are black wells with light text, like OpenRCT2's console window.
- Notes and warnings use the ticker style (a note) or a yellow window (a warning).

### GitHub

GitHub doesn't allow custom CSS in Markdown, so on GitHub the system comes through in pictures, labels, and writing:

- **Pictures.** Draw diagrams and banners as SVG in `docs/assets/`, with their own background painted in. Frame a banner or screenshot as a window: a title bar, two-pixel bevels, and square corners.
- **Callouts.** Use GitHub's alert syntax (`> [!NOTE]`, `> [!WARNING]`, `> [!CAUTION]`) and no more than one per section.
- **Issue and pull request labels.** Take label colours from the ramps, using the same meaning as the windows:

  | Label | Colour | Token |
  |---|---|---|
  | `bug` | `#a33b3b` | `--bordeaux-6` |
  | `enhancement` | `#379f17` | `--green-5` |
  | `documentation` | `#5ba3e7` | `--lightblue-7` |
  | `calibration`, `research` | `#d7a713` | `--yellow-6` |
  | `web ui` | `#a3937f` | `--brown-7` |
  | `question` | `#839797` | `--grey-7` |

- **Writing.** READMEs, issues, pull requests, devlog entries, and wiki pages all follow the [writing style guide](../writing-style.md).

## Accessibility checklist

Check each new screen or picture against this list before you merge it:

- [ ] Every text pair measures 4.5:1 or higher (3:1 for text 18 px and larger, or 14 px bold).
- [ ] Every state shown by colour is also shown in words.
- [ ] Every control can be reached and used with the keyboard, and shows the yellow focus outline.
- [ ] Every icon-only button has an `aria-label`.
- [ ] Every chart has a text description.
- [ ] The screen works at 400 px wide without scrolling sideways.
- [ ] Nothing moves when `prefers-reduced-motion` is set.

## Open questions

- **Exact ramp offsets.** Compare `tokens.css` with an OpenRCT2 screenshot of the ride, ride construction, and finances windows at 2x scale, and adjust a colour class if a window reads as the wrong shade.
- **Pixelify Sans.** Decide whether to ship the font with the web UI or stay with Verdana for titles.
- **Page texture.** The two-by-two checker reads as grass on most screens. Replace it with a drawn grass tile if it looks like noise on large monitors.
