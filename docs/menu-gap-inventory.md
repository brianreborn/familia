# Familia menu gap inventory (epic #733, milestone M5)

Inventory of the interactive menus on `main` at `81d4f62` (2026-11-23, America/Los_Angeles). Owner: X Bug Cartographer. This document records gaps; it does not implement the M1 key loop or the M4 UX work.

Standing rules (Brian, 2026-11-10, also in #476 and #733): six equal top-level items (Models, Harnesses, Agents, MCP servers, Tool sets, App store); the legacy catalog must reach everything and remains the fallback and the CLI; numeric entry must keep working; menus exit only on an explicit user quit, never on errors, finished actions, invalid input, or timeouts.

When docs and code disagree, this inventory follows the code and notes the disagreement.

## Surfaces inventoried

| Surface | Entry | Implementation |
|---|---|---|
| Home (Unix) | `./familia` | `scripts/familia_home.sh` + `scripts/home_catalog.py` |
| Legacy catalog (Unix) | `./familia menu`, `--legacy-menu`, or missing-gum fallback | `familia-menu.sh` + `scripts/menu-items.txt` |
| Home (Windows) | `familia.cmd` | `scripts/windows/familia-home.ps1` |
| Legacy catalog (Windows) | `familia.cmd menu` | `scripts/windows/familia-menu.ps1` |

The catalog has 152 rows in 19 groups. 149 have a POSIX command (visible in `familia-menu.sh`). 3 are Windows-only (empty POSIX command). 35 have no Windows command. Page size in the legacy menu is 7 (`familia-menu.sh` `page_size=7` at line 382).

## Counts by gap type

| Type | Count | Notes |
|---|---|---|
| Missing arrow-key navigation | 2 surfaces (legacy Unix + Windows) | Home uses `gum choose`, which already has arrows; legacy is numeric only. Owned by M1. |
| Missing numeric selection | 2 surfaces (home Unix + Windows) | Standing rule is broken on the gum home picker. |
| Premature exit / does not return | 2 (Unix + Windows fallback) | `fallback_legacy` / `Enter-Legacy` leave the home menu for good. Already listed in #476. |
| Item-set / docs inconsistencies | 4 | Interactive extras vs `--list-goals`, stale README, stale #476 body, Windows App store submenu missing extras. |
| Back-navigation / numbering / label inconsistencies | 6 | Empty Enter = Back; page-local numbers; Quit in a submenu exits the process; group names vs home titles; diamond proving-grounds label; two app groups. |
| Unreachable on Windows (empty command) | 35 rows | Some are platform-specific (Termux, Android, FreeBSD); several look unintentional (Hermes, Front door, unit tests, man page, proving grounds). |
| Mapped to an existing issue, no new issue | see below | #476, #733 M1/M3/M4/M6/M7, #676, #728 |

Top 5 (highest impact on the #733 redesign):

1. Legacy catalog has no arrow-key traversal (Unix and Windows), including no arrow/Home/End/PgUp/PgDn paging.
2. Home `gum choose` picker has no numeric entry, despite numbered `--list-goals` and the standing rule.
3. `fallback_legacy` / `Enter-Legacy` exec/exit away and never return to the home menu (#476 still open).
4. Interactive home item set disagrees with `--list-goals`, README, and the #476 write-up.
5. Back-navigation, page-local numbering, and labels are inconsistent across home, legacy, and Windows.

## 1. Missing arrow-key navigation

The legacy menu is a `read` loop over numeric choices. There is no raw-mode key reader, no highlight, and no Up/Down/Home/End/PgUp/PgDn handling.

- Unix: `familia-menu.sh` `menu()` at lines 381-469. Input is `read_line` (139-144) and `parse_menu_input` (158-182). Paging uses the characters `<` and `>` (lines 447-448), not arrow keys.
- Windows: `scripts/windows/familia-menu.ps1` uses `Read-Host` (around lines 372 and 406-407). Same numeric/`<`/`>` model, no arrows.

The home picker *does* use arrows, but only because it shells out to Charm gum:

- Unix: `pick()` in `scripts/familia_home.sh` lines 169-203, `gum choose --header ... --height 16`.
- Windows: `Pick-One` in `scripts/windows/familia-home.ps1` lines 122-139, same `gum choose`.

This is M1's job. A new sub-issue records the gap and points at M1; the key loop is not implemented here. The harness reports arrow reachability of the legacy top-level menu as FAIL on current `main`.

## 2. Missing numeric selection on the home menu

`--list-goals` prints `1) Models` ... `6) App store` (`scripts/home_catalog.py --list-home`, via `familia_home.sh` lines 81-83 and 357-363). The interactive loop never reads those numbers. `pick()` only accepts a `gum choose` selection.

Brian's standing rule on #733: "Numeric entry must keep working." That holds for the legacy catalog and is broken for the default `./familia` home on both Unix and Windows.

## 3. Exit-only-on-quit (remaining violations)

#476 already lists the rule and several premature-exit paths. Code on current `main` has fixed most of them. Still open:

- **Fallback never returns.** `fallback_legacy` in `scripts/familia_home.sh` lines 68-71 `exec bash "$ROOT/familia-menu.sh"`. After a missing/unusable gum (lines 115-120) or three gum failures (153-160), the user cannot get back to the six-item home. #476: "The home execs away and never returns."
- **Windows is the same, plus it exits after the legacy menu ends.** `Enter-Legacy` in `scripts/windows/familia-home.ps1` lines 57-62 runs the legacy menu and then `exit $LASTEXITCODE`.
- **Missing gum and no TTY exits 2** (`familia_home.sh` 116-118, 156-158). This is intentional (closed input is not a quit; tests encode it). Not filed as a new gap.
- **HUP exits 129, TERM exits 143** (`familia_home.sh` 43-44). Reasonable when the terminal is gone. Not filed.
- **Unknown CLI arg exits 2** (`familia_home.sh` 63). CLI, not an interactive session. Not filed.

Already fixed relative to the #476 write-up (do not re-file):

- Missing gum on a TTY now falls back instead of exiting 2 (`familia_home.sh` 115-120; `tests/test_home_menu.py` `test_missing_gum_falls_back_to_legacy_menu`).
- Gum cancel (Esc / exit 1 after 0.2s) stays in the menu (`pick()` 196-199).
- Action errors stay in the menu (`run_verb` 285-288, legacy `run_item` failure at `familia-menu.sh` 462).
- Ctrl-C stays in the home menu (`on_int` / `note_interrupt`, lines 35-42 and 74-78).
- Ctrl-C stays in the legacy menu. `familia-menu.sh` installs a POSIX `INT` trap only while the interactive menu is running (including `--pipe`). ^C at a prompt, at a value prompt, or during a child action cancels that step, prints `Use the Exit option to quit`, and redraws. `q` / `exit` still exits 0. `HUP` and `TERM` are not trapped. Child commands reset `INT` / `HUP` / `TERM` to the default so the action itself can be killed. `--list`, `--run`, and `--search` do not install the trap. The harness sends ^C (`pexpect` `sendintr`) and asserts this.
- Legacy EOF on a pipe exits 2, not 0 (`closed_input`; `test_legacy_eof_is_not_a_successful_quit`).
- No menu timeout was found.

`Quit` inside an area submenu (`familia_home.sh` 312, Windows `Enter-Area` 217) exits the process. That is an explicit quit, so it does not break the rule, but it is inconsistent with `Back` (see section 5; M4).

## 4. Unreachable and item-set mismatches

The interactive home `pick()` list (`familia_home.sh` 361-364) is:

Models, Harnesses, Agents, MCP servers, Tool sets, App store, Open llama-ui web cockpit, List all models, Configure all graphs, Legacy menu, Quit.

`--list-goals` numbers only the six areas, then describes "Legacy goals still on that menu" as Talk, Cockpit, Find more models, List all models, Configure all graphs, Search X, Install, Proving grounds, Legacy menu. Talk, Find more models, Search X, Install, and Proving grounds are **not** on the interactive home; they are only on the legacy catalog (Front door / Set up / Proving grounds groups). Cockpit, List all models, Configure all graphs, and Legacy menu **are** on the interactive home but are not numbered.

This is not a dead-end: those older goals are reachable via `Legacy menu` / `./familia --legacy-menu`. It is an item-set and labeling inconsistency (M3 / docs).

`tests/test_home_menu.py` `test_legacy_catalog_reaches_every_home_action` confirms every `home.<area>.<verb>` key plus `home.talk`, `home.find-models`, and `home.search-x` exist in the catalog. The Unix App store submenu also has `browse` and `web page` (`familia_home.sh` 296-318), with catalog keys `home.apps.browse` and `home.apps.web`. The Windows home submenu does not offer those two extras (`Enter-Area` in `familia-home.ps1` lines 208-211: only install/list/start/stop/status/Back/Quit). That is a Unix/Windows reachability split.

35 catalog rows have an empty Windows command, so they are hidden or impossible on Windows. Platform-specific examples (keep): Termux phone-agent rows, Android cockpit, FreeBSD poudriere, hosts.android/phones/watchdog. Likely unintentional: Hermes and guardian launch rows (lines 41-50), Front door `home.talk` / `home.find-models` / `home.search-x` (154-156), `test.unit`, `test.proving-grounds`, `help.man`, `setup.settings`. Related to M7.

3 rows are Windows-only (empty POSIX command): `setup.logon-task` (line 17), `adv.logon-task-remove` (109), `adv.numpy-wheel` (110). That is expected.

## 5. Back-navigation, numbering, and labels

- Empty input in a legacy group or search UI is Back (`familia-menu.sh` 445 and 354: `b|B|back|""`). At the top-level menu, empty input is ignored (397). Inconsistent.
- Page-local numbers: a 15-item group shows `1)`-`7)` on page 1 and `1)`-`n` again on later pages (`familia-menu.sh` 421-425). Items after the first page are not selectable by a stable catalog index; the user must type `>` first. There is no arrow or PgDn paging.
- App store Unix submenu adds `browse` / `web page`; other areas do not. Windows home omits those extras.
- Group titles in the legacy catalog do not match the six home names: "Self-improving harness (Harness2)" vs Harnesses, "Agents (hermes)" vs Agents, "Front door" for older goals, "App catalog" vs "App store", and "◆ Proving grounds (graded)" (line 121 area of `menu-items.txt`).
- `Quit` in a submenu exits the whole process (`familia_home.sh` 312) rather than returning to the six-item list. M4.

No breadcrumbs, no home-menu search/filter, and footer hints differ between home (gum header only) and legacy (`/word`, `n`/`N`, `b`, `q`). Those are M4's job; they are recorded here and not implemented.

## 6. Docs vs code

Follow the code.

- `README.md` "What now?" still describes default `./familia` as the old grouped legacy catalog ("Set up, Skills, Models, Agents, Harness2, Test, Hosts, three Advanced groups, Help"). Code opens the six-item home (`familia` lines 34-40). `QUICKSTART.md` is closer to the code but omits the extra interactive home items (cockpit, list models, configure graphs, Legacy menu).
- #476's body still describes today's gum home as seven goals (Talk, Cockpit, Find models, Search X, Install, Proving grounds, Legacy) and "a missing gum exits 2". Both are stale on current `main`.
- `familia_home.sh` comments correctly say six equal items and "the interactive menu exits only on Quit," but the interactive `pick()` list is the six items plus four extras plus Quit.

## 7. Mapped to existing work (do not duplicate)

| Topic | Maps to |
|---|---|
| Arrow-key / key loop, wraparound, highlight, terminal restore | #733 M1 (Race Reviewer) |
| Escape-sequence hardening, non-tty / TERM=dumb / piped stdin fallback | #733 M2 (Boundary Reviewer) |
| Six-category top-level structure, `menu-items.txt` registry, merge order | #733 M3 (Release Driver); umbrella spec #476 |
| Breadcrumbs, search/filter, footer hints, consistent submenus, rendering | #733 M4 (Continuity) |
| Hermes/guardian entries "wired into the new navigation" | #733 M6. Legacy already has Agents (hermes) and guardian launch rows (`menu-items.txt` 41-50). The new home Agents submenu is only install/list/start/stop/status. |
| Cross-platform terminal / Windows command coverage | #733 M7; the 35 empty Windows commands are filed as an M5 sub-issue for M7 to use |
| llama.cpp PGO as a menu command | #676 (open) |
| Select an alternate model without typing its full path | #728 (open) |
| Remaining "exec away" exit-rule item | #476 (open). M5 files a focused remaining-work sub-issue and links it, rather than re-stating the whole spec. |
| App catalog / protograph / model picking rows | #397/#412, #399/#408, #398/#401 (closed/merged) |
| Historical catalog-test failures | #52, #103, #105, #225-#228, #600 (closed) |

Reference write-ups that are not current gaps: #327 (menu refactor), #328-#331 (host-specific redesign notes).

## 8. Harness

`tests/menu_harness.py` walks the tree headlessly (`--dry-run`, isolated HOME, no `--apply`). It also sends Ctrl-C at the legacy prompt, at a value prompt, and during a child action, and checks that `exit` still quits 0 while `HUP` and `TERM` still end the process. `python3 tests/menu_harness.py` writes the report; `python3 -m pytest tests/test_menu_harness.py` is the test target. See the README "Menu test harness" section and TESTING.md.

-- X Bug Cartographer
