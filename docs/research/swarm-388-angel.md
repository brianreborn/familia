# FreeBSD: familia-start path resolution refuses test key files

Issue: https://github.com/brianreborn/familia/issues/388
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:00 PST
Approved-content-sha256: 798dded8f7ee375b3018a4838e0f2b6e07a11bf8bfc430a36a02e9a781ee9e63

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue Summary

The issue involves a problem with the `familia-start` script on FreeBSD. The script is unable to resolve test key files due to a path resolution issue. Specifically, the script is refusing to resolve paths that exist but are not valid keys, which is incorrect behavior.

### Proposed Approach

1. **Use Portable Resolver**: Replace the helper used for path resolution with a portable resolver like `realpath(1)` or `os.path.realpath` to ensure compatibility across different operating systems.
2. **Maintain Refuse Behavior**: Keep the behavior of refusing paths that cannot be resolved, as this is the correct behavior when a path truly cannot be resolved.
3. **Add Test Cases**: Add or extend test cases to verify that the portable resolver works correctly on FreeBSD-style temp paths.

### Risks

- **Portability Issues**: There might be issues with the portable resolver if it doesn't handle all edge cases correctly.
- **Performance Impact**: Using `realpath(1)` might introduce performance overhead, especially on large datasets.

### Test Ideas

- **FreeBSD Test Environment**: Run the proposed fix in a FreeBSD environment to ensure compatibility and correctness.
- **Additional Test Cases**: Add test cases that specifically test the behavior of the portable resolver on FreeBSD-style temp paths.

### Open Questions

- **Performance Testing**: Determine the performance impact of using the portable resolver on FreeBSD.
- **Edge Case Handling**: Ensure that the portable resolver handles all edge cases correctly, especially those related to dangling or unreadable key files.

-- swarm/angel
