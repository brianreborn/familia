# Settings panel: configure familia in a simple window

The panel is a small web page served by your own computer. It works with a mouse,
a keyboard alone, a single switch (scanning) or a screen reader. It does not
need JavaScript, so it also runs in old browsers on old hardware.

## Open it

- `./familia panel` (or the first menu item, **Configure in a simple window (mouse, keyboard or switch friendly)**)
- On Windows: `python scripts\panel.py`, or the same item in `familia.cmd`

It opens http://127.0.0.1:9932/ in your browser. `--no-browser` (or `NO_BROWSER=1`)
only prints the address; `--port N` picks another port. Stop it with Ctrl+C.
If the port is busy because the panel is already running, it says so and opens the
running one.

The panel is code-bootstraps-llama.cpp's `scripts/panel.py`. familia's
`scripts/panel.py` starts it and adds familia's pages from `scripts/panel_familia.py`.
Run `sh scripts/configure.sh` first if the panel says code-bootstraps-llama.cpp is missing.

## What you can change

| Page | What it does | Uses |
|---|---|---|
| Skills | Switch bundled skills on or off for an agent or pentest role. A skill that can't be switched on is listed with the reason, not shown as a checkbox: license-blocked, not vendored into green-zkillz yet, not for this agent, or tool-adding on a pentest role. | `scripts/skills.py` (same rules), graph.yaml edited one line, comments kept |
| Licenses | Every license your selection brings, with unknown, restrictive and custom ones first, excerpts and links. Accept with a tick box (a second box for unknown licenses). | `scripts/licenses.py`, same `.cache/familia/license-acceptance.json` and selection hash |
| Hermes agent | Choose one model or the whole graph. The page shows the `scripts/hermes.sh` command to run in a terminal; it starts nothing. Until `--model` / `--graph-mode` are in `scripts/hermes_harness.py`, it shows the plain `scripts/hermes.sh` command. | builds the command line |
| Harness2 | Off, propose or apply for each agent, off by default. Pentest roles are never offered and a request for one is refused. Independent of hermes. Shows "Not available yet" until `scripts/harness2.py` is in the checkout. | `scripts/harness2.py status` / `set` |
| Models and launch parameters | Each node's model, host and status; pick a node to see its exact launch flags (REQUIRED / RECOMMENDED, with their source). Read-only. | `scripts/validate_graph.py --explain NODE` |
| Basics, Speed and memory, Network, Agent tools, Starting up | The launcher settings `start.sh` reads, with plain names (the variable name is shown too). | `code-bootstraps-llama.cpp/.cache/panel.env` |

Turning a skill on asks you to accept the licenses of the new selection on the
same confirmation page, as `scripts/skills.py enable` does; if you don't tick the
box, graph.yaml is not changed.

## Every change is previewed, and can be undone

1. Change things on a page and press **Next: show what will change**.
2. The next page lists each change in words ("Model server port (PORT): default (9931) to 9944").
   Press **Save these changes**, **Go back and change them**, or **Cancel**.
3. The start page shows the last save with an **Undo the last save** button. Undo goes back
   one save at a time (the last 20 are kept in `code-bootstraps-llama.cpp/.cache/panel-undo/`).
   If something else changed the file after that save (an editor, `scripts/skills.py`), undo
   refuses rather than overwrite that change.

When a value is not allowed, nothing is saved. A box at the top lists the problems
with links to each field, and everything you typed stays filled in.

## Using it without a mouse

- **Keyboard:** Tab moves to the next group or button, arrow keys move inside a group of
  choices, Space ticks a box, Enter presses a button. The first Tab shows a "Skip to the
  main content" link. Focus is a thick orange outline.
- **Switch (scanning):** each page is short, choices are big radio buttons (one press picks one),
  and there are no drop-down lists, sliders, drag and drop, double-clicks or time limits.
  Tab order follows the page; nothing jumps around.
- **Mouse or touch:** every button, choice and link is at least 44 by 44 pixels, and the
  whole text of a choice is clickable.
- **Screen reader:** every control has a label; hints and errors are read with the field;
  groups have a legend; status messages are announced.
- **Zoom and contrast:** text is 18 px and scales with browser zoom. The layout is one column,
  checked at 200% with no sideways scrolling. Colours are black on white, and every button and
  field also has a border, so forced-colour (high-contrast) modes keep the outlines. That mode
  has not been tried on Windows yet.

## Remote use stays private

The panel listens on 127.0.0.1 only and never opens a LAN port. To use it from another
computer, tunnel over SSH and open the address there:

```sh
ssh -L 9932:127.0.0.1:9932 HOST     # HOST: your ssh alias for that machine
# then browse to http://127.0.0.1:9932/ on the computer you are sitting at
```

It answers only requests addressed to 127.0.0.1 or localhost, which blocks
DNS-rebinding pages. Every form carries a token from the running panel, so another
web page can't submit changes. Pages are never cached.

## Accessibility check

`python3 scripts/panel.py --a11y-check` renders every page (including error and
confirmation pages) and checks it with `code-bootstraps-llama.cpp/scripts/lib/a11y_check.py`,
which is stdlib only. It checks for: a language and title, one `<h1>` and a `<main>`,
a label on every control, a legend on every group of choices, no positive tabindex,
no duplicate ids, no broken `aria-describedby` or `#links`, alt text on images,
text on buttons and links, and no script or timed refresh. The tests
(`tests/test_panel_familia.py` and code-bootstraps `tests/test_panel.py`) run it.
It is not a full WCAG audit. Colour contrast and live screen-reader, voice-control and
switch-device testing are listed as open work in the accessible configuration panel issue.

## Audit of the previous panel (2026-10-19)

The panel before this change was one table of 29 raw variable names (`CTX`, `REPACK`, ...).
The accessibility check finds 32 problems in it, and a code read found more:

- No control had a label (29 unlabelled fields), the page had no language, `<h1>` or
  `<main>`, and the allowed values (`HINTS`) were never shown.
- Choices were drop-down lists with a blank first option, which is hard for switch users and
  is announced as "blank" by screen readers. On/off settings were the digits 0 and 1.
- Default-size controls (about 21 px tall), and the browser's thin default focus ring only.
- 29 fields and one Save button at the bottom on a single page meant about 30 switch steps
  to save one change.
- A rejected value showed "Rejected KEY." at the bottom of the page, not tied to the field
  or announced, and the form reloaded the saved values, so everything else typed was lost.
- No preview and no undo. `panel.env` was written in place, not atomically.
- Any web page open in the same browser could submit the form to 127.0.0.1:9932 (no token,
  no Host or Origin check).
- `EMBED_PORT` and `ENGINE_CHAT` were listed but every value was refused, so they could not
  be set from the panel or `configure.sh`.

All of these are fixed. The page still has no JavaScript and no dependencies beyond Python's
standard library.
