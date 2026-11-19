# FreeBSD port (preliminary) + poudriere build

Issue: https://github.com/brianreborn/familia/issues/37
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:34 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #37: FreeBSD Port (Preliminary) + Poudriere Build

### Issue Description

The goal is to create a preliminary FreeBSD port for `sysutils/familia` under the `packaging/freebsd/` overlay tree. The port should target FreeBSD 15.x (godslove, brianreborn/green-roomz#5). The port should be configured to build without building or archiving, and it should include scripts and wrappers in the appropriate directories. The port should also have run-time dependencies and options.

### Proposed Approach

1. **Create the Port Directory Structure:**
   - Create a directory structure under `packaging/freebsd/` for the FreeBSD port.
   - Place the port files (e.g., `Makefile`, `pkg-descr`, `pkg-plist`) in the appropriate directories.

2. **Configure the Port:**
   - Set the port to build without building or archiving (`NO_BUILD/NO_ARCH`).
   - Define the scripts and wrappers in the `${PREFIX}/libexec/familia` and `${PREFIX}/bin` directories.
   - Define the documentation and example files in the `${DOCSDIR}` and `${EXAMPLESDIR}` directories.

3. **Define Dependencies:**
   - Specify the run-time dependencies (`RUN_DEPENDS`) in the `Makefile`.
   - Use the `USES=python:run` flag to include Python dependencies.
   - Include other dependencies such as `devel/py-pyyaml@${PY_FLAVOR}`, `shells/bash`, `devel/git`, `net/rsync`, and `ftp/curl`.

4. **Define Options:**
   - Define the options (`OPTIONS`)

-- swarm/angel
