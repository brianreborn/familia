# Research bucket

Applies to the familia family of projects: familia, green-roomz,
code-bootstraps-llama.cpp and llama.SPY.

An issue in the research bucket is an idea, survey or exploration. It is:

- last priority: it sits behind every release milestone;
- not shown in the app store (`scripts/app_catalog.py` searches
  `label:applications -label:research`);
- not actionable: swarm-pull treats `research` as a block label, so no swarm
  worker claims it, even if it also carries `swarm-approved`.

## Where it lives

- Label `research` (gray) on each repo.
- Milestone `research` on each repo.
- User project "Research (last priority)":
  https://github.com/users/brianreborn/projects/4

## Putting an issue in the bucket

Add the `research` label, set the milestone to `research`, and add the issue
to the project. Do not close it. Do not use the bucket for release blockers,
must-land work, security fixes or issues with an active claim.

## Promoting an issue to active work

Only Brian promotes an issue. To promote it:

1. Remove the `research` label.
2. Set a release milestone (for example v0.5.0) in place of `research`.
3. Add `swarm-approved` if swarm workers should take it, or assign it.
4. Remove it from the project, or leave it there as history.

Once the label is off, swarm-pull and the app store see the issue again.
