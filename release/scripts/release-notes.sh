#!/bin/sh
# release-notes.sh: regenerate the GitHub issue/PR index in a release notes
# file. Read-only against GitHub. ASCII output only. Idempotent for a given
# GitHub state.
#
# Usage:
#   sh release/scripts/release-notes.sh
#   sh release/scripts/release-notes.sh --write docs/releases/v0.3.0.md
#   sh release/scripts/release-notes.sh --version 0.3.0 --stdout
#
# Queries (read-only):
#   gh issue list --repo REPO --milestone MILESTONE --state closed --limit 200
#     --json number,title,url
#   gh issue list --repo REPO --milestone MILESTONE --state open --limit 200
#     --json number
#   gh pr list --repo REPO --search "milestone:MILESTONE is:merged base:main"
#     --state merged --limit 200 --json number,title,url,baseRefName
#   For each closed issue N, GraphQL closedByPullRequestsReferences (merged
#   to main only), so closing PRs are included even when they are not on the
#   milestone themselves.
set -eu
case "${1:-}" in
  -h|--help)
    cat <<'USAGE'
release-notes.sh: Rebuild the generated issue and pull-request lists for a
familia release notes file from the GitHub milestone. Read-only against
GitHub. Titles are forced to ASCII (non-ASCII is transliterated or stripped).

Usage:
  sh release/scripts/release-notes.sh [--version X.Y.Z] [--repo OWNER/NAME]
     [--write PATH | --stdout]

  --version X.Y.Z   Release version (default: 0.3.0). Milestone is vX.Y.Z.
  --repo OWNER/NAME GitHub repo (default: from gh/git, else brianreborn/familia)
  --write PATH      Create or update PATH (default: docs/releases/vX.Y.Z.md)
  --stdout          Print the generated lists only; do not write a file

Example: sh release/scripts/release-notes.sh --write docs/releases/v0.3.0.md
USAGE
    exit 0
    ;;
esac

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"

VERSION=0.3.0
REPO=""
WRITE_MODE=1
OUT_PATH=""
STDOUT_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      VERSION=${2:-}
      [ -n "$VERSION" ] || { printf '%s\n' "release-notes.sh: --version needs a value" >&2; exit 2; }
      shift
      ;;
    --repo)
      REPO=${2:-}
      [ -n "$REPO" ] || { printf '%s\n' "release-notes.sh: --repo needs a value" >&2; exit 2; }
      shift
      ;;
    --write)
      WRITE_MODE=1
      STDOUT_ONLY=0
      OUT_PATH=${2:-}
      [ -n "$OUT_PATH" ] || { printf '%s\n' "release-notes.sh: --write needs a path" >&2; exit 2; }
      shift
      ;;
    --stdout)
      STDOUT_ONLY=1
      WRITE_MODE=0
      ;;
    -h|--help)
      # already handled; keep for mid-argv use
      exec "$0" --help
      ;;
    *)
      printf '%s\n' "release-notes.sh: unknown arg $1" >&2
      exit 2
      ;;
  esac
  shift
done

# Version must be plain dotted digits so the milestone title stays ASCII and
# cannot be turned into an unexpected gh search.
case "$VERSION" in
  *[!.0-9]*|"")
    printf '%s\n' "release-notes.sh: version must be dotted digits (got: $VERSION)" >&2
    exit 2
    ;;
esac

MILESTONE="v${VERSION}"
if [ -z "$OUT_PATH" ]; then
  OUT_PATH="docs/releases/v${VERSION}.md"
fi

command -v gh >/dev/null 2>&1 || { printf '%s\n' "release-notes.sh: gh is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf '%s\n' "release-notes.sh: python3 is required" >&2; exit 1; }

if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)
fi
if [ -z "$REPO" ]; then
  REPO=$(git -C "$ROOT" remote get-url origin 2>/dev/null | sed -n 's#.*github.com[:/]\(.*\)\.git$#\1#p; s#.*github.com[:/]\([^/]*/[^/]*\)$#\1#p' | head -n 1)
fi
if [ -z "$REPO" ]; then
  REPO=brianreborn/familia
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# 1) Closed milestone issues (issues only; milestone totals also count PRs).
gh issue list --repo "$REPO" --milestone "$MILESTONE" --state closed --limit 200 \
  --json number,title,url > "$TMPDIR/closed.json"

# 2) Open milestone issues (count only).
gh issue list --repo "$REPO" --milestone "$MILESTONE" --state open --limit 200 \
  --json number > "$TMPDIR/open.json"

# 3) PRs merged to main that carry the milestone.
gh pr list --repo "$REPO" --search "milestone:${MILESTONE} is:merged base:main" \
  --state merged --limit 200 --json number,title,url,baseRefName \
  > "$TMPDIR/milestone_prs.json"

# 4) PRs that close those issues, even if the PR is not on the milestone.
python3 - "$REPO" "$TMPDIR" <<'PY'
import json, subprocess, sys

repo = sys.argv[1]
tmpdir = sys.argv[2]
with open(tmpdir + "/closed.json", encoding="utf-8") as f:
    closed = json.load(f)

owner, name = repo.split("/", 1)
nodes = []
for issue in closed:
    n = int(issue["number"])
    query = """
    query($owner:String!, $name:String!, $n:Int!) {
      repository(owner:$owner, name:$name) {
        issue(number:$n) {
          closedByPullRequestsReferences(first:20) {
            nodes { number title url merged state baseRefName }
          }
        }
      }
    }
    """
    proc = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", "query=" + query,
            "-F", "owner=" + owner,
            "-F", "name=" + name,
            "-F", "n=" + str(n),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or ("graphql failed for issue %s\n" % n))
        sys.exit(1)
    data = json.loads(proc.stdout)
    issue_data = (
        data.get("data", {}).get("repository", {}).get("issue") or {}
    )
    refs = (
        issue_data.get("closedByPullRequestsReferences", {}) or {}
    ).get("nodes") or []
    for node in refs:
        node["closes"] = n
        nodes.append(node)

with open(tmpdir + "/closing_prs.json", "w", encoding="utf-8") as f:
    json.dump(nodes, f)
PY

# Build lists, write or print. All markdown is ASCII.
export RN_VERSION="$VERSION"
export RN_MILESTONE="$MILESTONE"
export RN_REPO="$REPO"
export RN_ROOT="$ROOT"
export RN_OUT="$OUT_PATH"
export RN_STDOUT="$STDOUT_ONLY"
export RN_TMPDIR="$TMPDIR"
python3 <<'PY'
import json, os, re, sys, unicodedata

version = os.environ["RN_VERSION"]
milestone = os.environ["RN_MILESTONE"]
repo = os.environ["RN_REPO"]
root = os.environ["RN_ROOT"]
out_path = os.environ["RN_OUT"]
stdout_only = os.environ["RN_STDOUT"] == "1"
tmpdir = os.environ["RN_TMPDIR"]

CLOSED_BEGIN = "<!-- begin generated closed-issues -->"
CLOSED_END = "<!-- end generated closed-issues -->"
PRS_BEGIN = "<!-- begin generated merged-prs -->"
PRS_END = "<!-- end generated merged-prs -->"
PLANNED_BEGIN = "<!-- begin generated planned -->"
PLANNED_END = "<!-- end generated planned -->"

def ascii_text(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    out = [].__class__(c if ord(c) < 128 else " " for c in s)
    s = "".join(out)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def load(name):
    with open(os.path.join(tmpdir, name), encoding="utf-8") as f:
        return json.load(f)

def md_issue_line(item, kind="issues"):
    n = int(item["number"])
    title = ascii_text(item.get("title") or "")
    url = "https://github.com/%s/%s/%d" % (repo, kind, n)
    # Prefer the API url when it is already ASCII https for this repo.
    raw = item.get("url") or url
    if re.match(r"^https://github.com/%s/%s/%d$" % (re.escape(repo), kind, n), raw or ""):
        url = raw
    return "- [#%d](%s) %s" % (n, url, title)

closed = load("closed.json")
open_issues = load("open.json")
milestone_prs = load("milestone_prs.json")
closing_prs = load("closing_prs.json")

if len(closed) >= 200:
    sys.stderr.write("release-notes.sh: closed issue list hit the 200-item cap\n")
    sys.exit(1)
if len(open_issues) >= 200:
    sys.stderr.write("release-notes.sh: open issue list hit the 200-item cap\n")
    sys.exit(1)
if len(milestone_prs) >= 200:
    sys.stderr.write("release-notes.sh: merged milestone PR list hit the 200-item cap\n")
    sys.exit(1)

open_count = len(open_issues)

prs = {}
for item in milestone_prs:
    if (item.get("baseRefName") or "") != "main":
        continue
    prs[int(item["number"])] = item
for item in closing_prs:
    if not item.get("merged"):
        continue
    if (item.get("state") or "").upper() != "MERGED":
        continue
    if (item.get("baseRefName") or "") != "main":
        continue
    prs[int(item["number"])] = item

closed_lines = [md_issue_line(i, "issues") for i in sorted(closed, key=lambda x: int(x["number"]))]
pr_lines = [md_issue_line(i, "pull") for i in sorted(prs.values(), key=lambda x: int(x["number"]))]

if not closed_lines:
    closed_block = "None yet.\n"
else:
    closed_block = "\n".join(closed_lines) + "\n"
if not pr_lines:
    pr_block = "None yet.\n"
else:
    pr_block = "\n".join(pr_lines) + "\n"

planned_block = (
    "%d issues remain open on the %s milestone. "
    "Re-run the generator for an updated count. "
    "The GitHub milestone total also counts pull requests.\n" % (open_count, milestone)
)

generated = "\n".join([
    "## Closed issues",
    "",
    CLOSED_BEGIN,
    closed_block.rstrip("\n"),
    CLOSED_END,
    "",
    "## Merged pull requests",
    "",
    PRS_BEGIN,
    pr_block.rstrip("\n"),
    PRS_END,
    "",
    "## Planned / still open",
    "",
    PLANNED_BEGIN,
    planned_block.rstrip("\n"),
    PLANNED_END,
    "",
])

if stdout_only:
    sys.stdout.write(generated)
    sys.exit(0)

skeleton = """# familia v%s release notes

- Version: %s
- Status: draft
- Target date: not set yet

## Summary

Draft in progress; see list below.

## Highlights

To be written.

%s\n## Known issues

Standing product issues live in docs/known-issues.md. Release-specific items will be listed here as they are confirmed.

## Upgrade notes

No upgrade steps have been written for this draft yet.

## How this file is generated

This file is the working index for the %s release. Hand-written sections can be edited in place. The Closed issues, Merged pull requests, and Planned / still open count are regenerated from GitHub with:

    sh release/scripts/release-notes.sh --write docs/releases/v%s.md

The script is read-only against GitHub. It lists closed issues on the %s milestone, pull requests merged to main that are on that milestone or that close those issues, and the count of still-open milestone issues.

-- Writer (writing/review agent for Brian)
""" % (version, version, generated, milestone, version, milestone)

def replace_section(text, begin, end, inner):
    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    if not pattern.search(text):
        raise SystemExit(
            "release-notes.sh: missing markers %s .. %s in %s" % (begin, end, out_path)
        )
    return pattern.sub(begin + "\n" + inner.rstrip("\n") + "\n" + end, text, count=1)

path = out_path
if not os.path.isabs(path):
    path = os.path.join(root, path)

if not os.path.exists(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_text = skeleton
else:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = replace_section(text, CLOSED_BEGIN, CLOSED_END, closed_block)
    text = replace_section(text, PRS_BEGIN, PRS_END, pr_block)
    text = replace_section(text, PLANNED_BEGIN, PLANNED_END, planned_block)
    new_text = text

# Final ASCII gate: refuse to write non-ASCII.
bad = [i + 1 for i, line in enumerate(new_text.splitlines()) if any(ord(c) > 127 for c in line)]
if bad:
    raise SystemExit("release-notes.sh: non-ASCII would be written at lines %s" % (bad[:10],))

if not new_text.endswith("\n"):
    new_text += "\n"

with open(path, "w", encoding="ascii", newline="\n") as f:
    f.write(new_text)

sys.stdout.write("wrote %s\n" % out_path)
PY
