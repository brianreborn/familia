# Continuous integration

The `tests` workflow runs the Python test suite and a separate `pin-integrity`
job on pull requests, pushes to `main`, and manual dispatches.

## Pin integrity

`pins.txt` contains both repository pins and ontology rows. Repository rows
have four tab-separated fields: name, full lowercase 40-hex commit SHA, HTTPS
GitHub repository URL, and role. `node` and `transport` rows are capability
names, not repository pins. The pin gate checks the row format, rejects the
known-invalid `b1b770d` llama.cpp commit prefix, and performs a depth-one fetch
of every pinned commit from its declared repository. It needs no PAT or
repository secret: it fetches this public source and the pinned public
repositories anonymously, and the job has no GitHub token permissions.

Run the exact local gate with:

```sh
python3 scripts/check_pins.py
```

The command needs `git` and network access. Format and policy unit tests are in
`tests/test_pins.py` and run as part of the normal pytest job.

For a repository under `brianreborn/*` that GitHub identifies as a fork, the
gate also checks whether a pin remains reachable from the default branch or a
tag. If a pin is reachable only from non-default branches, it prints a warning:
deleting those branch refs would make future pin syncs fail. This durability
warning does not turn an otherwise fetchable pin into a failure.
