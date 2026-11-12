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
#   gh pr list --repo REPO --state merged --base main --search "merged:>=TAG_DATE"
#     --limit 500 --json number,title,url,mergedAt (since previous tag)
set -eu
case "${1:-}" in
  -h|--help)
    cat <<'USAGE'
release-notes.sh: Rebuild the generated issue and pull-request lists for a
familia release notes file from the GitHub milestone and merged PRs.
Read-only against GitHub. Titles are forced to ASCII (non-ASCII is
transliterated or stripped).

Usage:
  sh release/scripts/release-notes.sh [--version X.Y.Z] [--repo OWNER/NAME]
     [--since-tag TAG] [--write PATH | --stdout]

  --version X.Y.Z   Release version (default: 0.3.0). Milestone is vX.Y.Z.
  --repo OWNER/NAME GitHub repo (default: from gh/git, else brianreborn/familia)
  --since-tag TAG   Previous release tag (default: auto-detected or v0.2.0-pre-alpha)
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
SINCE_TAG=""
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
    --since-tag)
      SINCE_TAG=${2:-}
      [ -n "$SINCE_TAG" ] || { printf '%s\n' "release-notes.sh: --since-tag needs a value" >&2; exit 2; }
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

# Confinement check for write mode: target path must be docs/releases/vX.Y.Z.md
if [ "$WRITE_MODE" = 1 ]; then
  case "$OUT_PATH" in
    docs/releases/v*.md|*/docs/releases/v*.md)
      ;;
    *)
      printf '%s\n' "release-notes.sh: --write path must be under docs/releases/vX.Y.Z.md" >&2
      exit 2
      ;;
  esac
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

# Detect since-tag if not provided
if [ -z "$SINCE_TAG" ]; then
  # Try to find previous tag before vX.Y.Z
  SINCE_TAG=$(git -C "$ROOT" tag -l "v*" --sort=-creatordate 2>/dev/null | grep -v "^${MILESTONE}$" | head -n 1 || true)
fi
if [ -z "$SINCE_TAG" ]; then
  SINCE_TAG="v0.2.0-pre-alpha"
fi

# Determine since_tag ISO timestamp
SINCE_DATE=""
if git -C "$ROOT" rev-parse -q --verify "refs/tags/${SINCE_TAG}" >/dev/null 2>&1; then
  SINCE_DATE=$(git -C "$ROOT" log -1 --format="%aI" "${SINCE_TAG}" 2>/dev/null || true)
fi
if [ -z "$SINCE_DATE" ]; then
  SINCE_DATE="2026-10-28T18:16:05Z"
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

# 5) All PRs merged to main since previous tag date
SEARCH_DATE=$(echo "$SINCE_DATE" | cut -d'T' -f1)
gh pr list --repo "$REPO" --state merged --base main --search "merged:>=${SEARCH_DATE}" \
  --limit 500 --json number,title,url,mergedAt > "$TMPDIR/all_merged.json"

# Build lists, write or print. All markdown is ASCII.
export RN_VERSION="$VERSION"
export RN_MILESTONE="$MILESTONE"
export RN_SINCE_TAG="$SINCE_TAG"
export RN_SINCE_DATE="$SINCE_DATE"
export RN_REPO="$REPO"
export RN_ROOT="$ROOT"
export RN_OUT="$OUT_PATH"
export RN_STDOUT="$STDOUT_ONLY"
export RN_TMPDIR="$TMPDIR"
python3 <<'PY'
import json, os, re, sys, tempfile, unicodedata

version = os.environ["RN_VERSION"]
milestone = os.environ["RN_MILESTONE"]
since_tag = os.environ["RN_SINCE_TAG"]
since_date = os.environ["RN_SINCE_DATE"]
repo = os.environ["RN_REPO"]
root = os.environ["RN_ROOT"]
out_path = os.environ["RN_OUT"]
stdout_only = os.environ["RN_STDOUT"] == "1"
tmpdir = os.environ["RN_TMPDIR"]

CLOSED_BEGIN = "<!-- begin generated closed-issues -->"
CLOSED_END = "<!-- end generated closed-issues -->"
PRS_BEGIN = "<!-- begin generated merged-prs -->"
PRS_END = "<!-- end generated merged-prs -->"
SINCE_BEGIN = "<!-- begin generated merged-since-tag -->"
SINCE_END = "<!-- end generated merged-since-tag -->"
PLANNED_BEGIN = "<!-- begin generated planned -->"
PLANNED_END = "<!-- end generated planned -->"

def ascii_text(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c if ord(c) < 128 else " " for c in s)
    s = re.sub(r"[ \t]+", " ", s)
    # Strip HTML comment delimiters
    s = s.replace("<!--", "").replace("-->", "")
    # Escape brackets to prevent breaking Markdown links
    s = s.replace("[", "\\[").replace("]", "\\]")
    return s.strip()

def load(name):
    with open(os.path.join(tmpdir, name), encoding="utf-8") as f:
        return json.load(f)

def md_issue_line(item, kind="issues"):
    n = int(item["number"])
    title = ascii_text(item.get("title") or "")
    url = "https://github.com/%s/%s/%d" % (repo, kind, n)
    raw = item.get("url") or url
    if re.match(r"^https://github.com/%s/%s/%d$" % (re.escape(repo), kind, n), raw or ""):
        url = raw
    return "- [#%d](%s) %s" % (n, url, title)

closed = load("closed.json")
open_issues = load("open.json")
milestone_prs = load("milestone_prs.json")
closing_prs = load("closing_prs.json")
all_merged = load("all_merged.json")

if len(closed) >= 200:
    sys.stderr.write("release-notes.sh: closed issue list hit the 200-item cap\n")
    sys.exit(1)
if len(open_issues) >= 200:
    sys.stderr.write("release-notes.sh: open issue list hit the 200-item cap\n")
    sys.exit(1)
if len(milestone_prs) >= 200:
    sys.stderr.write("release-notes.sh: merged milestone PR list hit the 200-item cap\n")
    sys.exit(1)
if len(all_merged) >= 500:
    sys.stderr.write("release-notes.sh: all merged PR list hit the 500-item cap\n")
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

# Filter all_merged to strictly >= since_date
filtered_since = [p for p in all_merged if (p.get("mergedAt") or "") >= since_date]

closed_lines = [md_issue_line(i, "issues") for i in sorted(closed, key=lambda x: int(x["number"]))]
pr_lines = [md_issue_line(i, "pull") for i in sorted(prs.values(), key=lambda x: int(x["number"]))]
since_lines = [md_issue_line(i, "pull") for i in sorted(filtered_since, key=lambda x: int(x["number"]))]

if not closed_lines:
    closed_block = "None yet.\n"
else:
    closed_block = "\n".join(closed_lines) + "\n"

if not pr_lines:
    pr_block = "None yet.\n"
else:
    pr_block = "\n".join(pr_lines) + "\n"

if not since_lines:
    since_block = "None yet.\n"
else:
    since_block = "\n".join(since_lines) + "\n"

planned_block = (
    "%d issues remain open on the %s milestone. "
    "Re-run the generator for an updated count. "
    "The GitHub milestone total also counts pull requests.\n" % (open_count, milestone)
)

generated = "\n".join([
    "## Merged to main since %s" % since_tag,
    "",
    SINCE_BEGIN,
    since_block.rstrip("\n"),
    SINCE_END,
    "",
    "## Closed issues (milestone %s)" % milestone,
    "",
    CLOSED_BEGIN,
    closed_block.rstrip("\n"),
    CLOSED_END,
    "",
    "## Merged pull requests (milestone %s)" % milestone,
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

This file is the working index for the %s release. Hand-written sections can be edited in place. The Merged to main since %s, Closed issues, Merged pull requests, and Planned / still open count are regenerated from GitHub with:

    sh release/scripts/release-notes.sh --write docs/releases/v%s.md

The script is read-only against GitHub. It lists pull requests merged to main since %s, closed issues on the %s milestone, pull requests merged to main that are on that milestone or that close those issues, and the count of still-open milestone issues.
""" % (version, version, generated, milestone, since_tag, version, since_tag, milestone)

def replace_section(text, begin, end, inner):
    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    if not pattern.search(text):
        return None
    return pattern.sub(lambda _m: begin + "\n" + inner.rstrip("\n") + "\n" + end, text, count=1)

path = out_path
if not os.path.isabs(path):
    path = os.path.join(root, path)

# Refuse symlinks
if os.path.islink(path):
    raise SystemExit("release-notes.sh: refusing to write through symlink %s" % path)

if not os.path.exists(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_text = skeleton
else:
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # If the file does not have the since_tag block yet, insert it before Closed issues
    if SINCE_BEGIN not in text:
        since_section = "\n".join([
            "## Merged to main since %s" % since_tag,
            "",
            SINCE_BEGIN,
            since_block.rstrip("\n"),
            SINCE_END,
            "",
        ])
        if "## Closed issues" in text:
            text = text.replace("## Closed issues", since_section + "## Closed issues", 1)
        else:
            text = text + "\n" + since_section

    res = replace_section(text, CLOSED_BEGIN, CLOSED_END, closed_block)
    if res is not None:
        text = res
    res = replace_section(text, PRS_BEGIN, PRS_END, pr_block)
    if res is not None:
        text = res
    res = replace_section(text, SINCE_BEGIN, SINCE_END, since_block)
    if res is not None:
        text = res
    res = replace_section(text, PLANNED_BEGIN, PLANNED_END, planned_block)
    if res is not None:
        text = res

    # Remove template signature if present
    text = text.replace("\n-- Writer (writing/review agent for Brian)\n", "\n")
    if text.endswith("\n-- Writer (writing/review agent for Brian)"):
        text = text[:-len("\n-- Writer (writing/review agent for Brian)")] + "\n"
    new_text = text

# Final ASCII gate: refuse to write non-ASCII.
bad = [i + 1 for i, line in enumerate(new_text.splitlines()) if any(ord(c) > 127 for c in line)]
if bad:
    raise SystemExit("release-notes.sh: non-ASCII would be written at lines %s" % (bad[:10],))

if not new_text.endswith("\n"):
    new_text += "\n"

dir_name = os.path.dirname(path)
fd, tmp_file = tempfile.mkstemp(dir=dir_name, prefix=".rn-tmp-", text=True)
with open(fd, "w", encoding="ascii", newline="\n") as f:
    f.write(new_text)
    f.flush()
    os.fsync(f.fileno())

os.replace(tmp_file, path)

sys.stdout.write("wrote %s\n" % out_path)
PY
