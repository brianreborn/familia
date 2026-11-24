---
name: release-notes
description: Use when starting, updating, or regenerating familia release notes (docs/releases/vX.Y.Z.md) from the GitHub milestone, closed issues, and PRs merged to main.
---

# familia release notes

The release notes file is the main index for a release. It lists and links
every issue and pull request in the release, can be edited by hand at any
time, and its generated lists can be rebuilt from GitHub at any time.

## Layout

- Notes: `docs/releases/vX.Y.Z.md` (one file per release).
- Helper: `release/scripts/release-notes.sh` (read-only against GitHub).
- This skill: `release/skills/release-notes/SKILL.md`.

## Rules

- ASCII only. The script forces titles to ASCII; keep hand-written text ASCII.
- Branch from `main`, open a draft PR to `main`. Never target `development`.
- Signed commits (`git commit -s`), no force push.
- No placeholders (no TODO, TBD, XXX, `<VERSION>`) in committed text.
- Only text between the `<!-- begin generated ... -->` and
  `<!-- end generated ... -->` markers is rewritten by the script. Everything
  else (summary, highlights, upgrade notes, known issues) is hand-written and
  preserved.

## Start a new release file

1. `git fetch origin && git switch -c docs/release-notes-vX.Y.Z origin/main`
2. Make sure the GitHub milestone `vX.Y.Z` exists and holds the release issues.
3. `sh release/scripts/release-notes.sh --version X.Y.Z --write docs/releases/vX.Y.Z.md`
4. Fill in the hand-written sections; link `docs/known-issues.md` for the
   standing known-issues list instead of copying it.
5. Commit with `git commit -s`, push, open a draft PR to `main`. Put the
   regenerate command in the PR body.

## Update an existing release file

1. `sh release/scripts/release-notes.sh --version X.Y.Z --write docs/releases/vX.Y.Z.md`
2. Review `git diff`; only generated blocks should change unless you edited
   prose on purpose. Running it twice with no GitHub change must give no diff.
3. Commit with `git commit -s` and push to the release-notes branch.

## What the script queries

- Closed issues on milestone `vX.Y.Z`.
- Open issues on the milestone (listed as still planned).
- PRs merged to `main` on the milestone, plus every PR merged to `main` that
  closed a milestone issue (GraphQL `closedByPullRequestsReferences`), so
  closing PRs show up even when they are not on the milestone themselves.

## Checks before pushing

- `LC_ALL=C grep -n '[^ -~]' docs/releases/vX.Y.Z.md` prints nothing.
- `grep -nE 'TODO|TBD|XXX' docs/releases/vX.Y.Z.md` prints nothing.
- Regeneration is idempotent (second run, empty `git diff`).

## Known gaps

- Milestone counts on GitHub include PRs; the notes count issues only.
- PRs that close milestone issues should also be put on the milestone.
- Unmilestoned PRs merged to main since previous release tag are tracked under the "Merged to main since <tag>" block.
