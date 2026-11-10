---
name: ideas-from-x-posts
description: >-
  When asked, collect Brian's retweets, quote-posts, bookmarks and likes
  from his X accounts, extract promising ideas, and attach the source
  post references to an existing GitHub issue or, after the review gate,
  to a new issue on the most appropriate project. Use when he asks to
  integrate recent X interactions, classify a batch, or decide whether
  an interaction should refine an existing issue or become a new one.
---

# Ideas from X interactions

Agent/tool/MCP-agnostic skill for on-demand integration of Brian's
X (Twitter) interactions into GitHub issues.

This file specifies the procedure. It does not name a particular
agent, connector, or tool. Where this skill and the live issue
tracker or in-repo markdown disagree, follow the live record and
note the inconsistency in the run report.

## Purpose

Keep a current, deduplicated map from Brian's X interactions to the
right work item:

- When asked, collect retweets (RT), quote-posts (QRT), bookmarks, and
  likes from `@born_brian85001` and `@BrianReborn_alt`. Original posts
  and replies are out of scope.
- `@BrianReborn_alt` is the primary source for newest-model discoveries
  among those interactions. Both accounts are in scope every run.
- For each interaction, confirm its relevance to a Brian project and
  integrate anything with a plausible fit.
- Prefer refining an existing issue over opening a duplicate.
- When a new issue is justified, file it on the most appropriate repo
  (familia is not the default catch-all), with the X source references
  in the body.
- A new `rt-idea` issue needs three independent reviews. Every other
  new issue (survey, research-backlog, and similar) needs two.
  Signed reviewer comments count as approvals. A signed comment that
  only adds a source URL or a verified fact to an existing issue needs
  no review.

This process is intake and routing. It does not implement the idea,
open a branch or pull request, or merge anything. Vetted issues
(those that have passed the review gate) are intended to be picked
up for work under `DESIGN.md`, the familia swarm / super-project
design document, and only with the explicit approval of an
administrator. Intake never schedules or starts that work itself.

## When to run

Run only when Brian requests it (for example: "integrate recent
RTs/QRTs/bookmarks/likes", "classify this window", "route this
account's reposts"). There is no schedule and no scheduler. Do not
start a second run of the same request while one is still in
progress.

Label times in America/Los_Angeles as "PT".

## Inputs

- The two account handles: `@born_brian85001`, `@BrianReborn_alt`.
- An optional window or hint from Brian. If he does not give one,
  discover what is new by the method in New vs already integrated.
- Read access to the issue trackers and markdown of the routing repos
  (see Routing).
- Already-cited `x.com` / `twitter.com` status URLs and numeric post
  ids in issue bodies, comments, and in-repo `.md` files. That record
  is the canonical state.
- This skill, plus the process limits and guardrails below.

Do not maintain a cursor file, state file, or private inventory as the
source of truth. Scratch notes for a single run may be used and then
discarded; they must not be cited in a public issue in place of source
URLs, and they are not the process state.

## Capabilities (generic)

Use whatever implementations are available. Do not hard-require a named
connector.

- An X read capability:
  - Public or otherwise read-only listing of a user's retweets and
    quote-posts; fetch a post by id; expand referenced posts and
    unwrapped URLs.
  - An authenticated, read-only view of Brian's own accounts for
    bookmarks and likes. Authentication is only to read those private
    interaction lists. Do not create, delete, or otherwise manage
    bookmarks or likes, and do not post, reply, follow, or DM.
- An issue-tracker capability: search issues and comments across the
  routing repos; read an issue; comment; open an issue; apply existing
  labels. Create a label only if the repo already uses it elsewhere or
  Brian has approved the name.
- A repository-read capability: search `.md` files in the routing
  repos for post ids and X URLs.
- Local models, when they can do classification or summarization at
  acceptable quality. Offload that work locally rather than burning
  hosted capacity. Hosted reads of X, the issue tracker, and repo
  markdown are still allowed when a local path cannot do them.

If a required capability is missing, stop and report what is missing.
Do not sign in in a way that can write to X, and do not scrape around
a failed login.

## Canonical state (issues and repo markdown)

GitHub issues (titles, bodies, comments, labels) and other `.md`
references in the routing repos are the canonical state of this
process. There is no separate state file and no since-cursor.

Dedupe key: the numeric post id. Prefer the URL form
`https://x.com/<handle>/status/<id>` when the handle is known. Treat
these as the same post:

- `https://x.com/<handle>/status/<id>`
- `https://x.com/i/status/<id>`
- `https://twitter.com/<handle>/status/<id>`
- `https://twitter.com/i/status/<id>`

Always include the numeric id. Also index the original (referenced)
post id for retweets and quotes, so a later quote, bookmark, or like
of the same original can attach to the same issue.

An interaction is already integrated when its post id, or the original
it retweets or quotes, already appears in an issue body, a comment, or
an in-repo `.md` file on a routing repo. Do not file it again. A later
run may add a signed source-only comment when there is new substance
(a new related interaction, a corrected URL, or a verified fact), not
to repeat the same FYI. Those source-only comments need no review.

## New vs already integrated

Backfill is implicit. Use any reasonable method to decide what is a
new interaction, including:

- Search issues, comments, and in-repo `.md` files for numeric post
  ids and X status URLs already cited.
- Walk Brian's RT, QRT, bookmark, and like histories from the newest
  item backward until the recent stretch is already cited, then stop
  (already-integrated interactions are the natural end of the walk,
  not a calendar cutoff).
- If he names a window or a set of posts, use that and still dedupe
  against the canonical record.

Do not silently rescan an unbounded history when a backward walk has
already hit a stretch of cited interactions, unless he asks for a
full backfill.

If search or listing returns nothing, treat that as unproven, not as
"no interactions". Loosen the query, try another listing method, and
record a gap in the run report rather than assuming the work is done.

## Step-by-step procedure

1. Load this skill. Confirm the request is to integrate RT, QRT,
   bookmark, and/or like interactions (ignore originals and replies
   unless he explicitly expands the scope for that run).

2. Search the routing repos' issues, comments, and `.md` files for
   already-cited post ids and X URLs. That set is the baseline for
   what is already integrated.

3. Read, do not write, from X. For each account, collect retweets,
   quote-posts, bookmarks, and likes that are not already integrated.
   Walk backward until hitting already-integrated interactions, or
   until a window he named is covered. Expand referenced posts and
   unwrap t.co (or equivalent) URLs. Re-fetch the original of a
   repost; do not trust truncated repost text. Bookmarks and likes
   use the authenticated read-only view of Brian's own account.

4. For each new interaction, record (in the issue or comment you may
   write, not in a private state file): post id, URL, author, created
   or interacted time in PT, type (retweet, quote, bookmark, or like),
   short text or quote, expanded links, any media-only caveat
   ("link or list is in an image; not guessed"), and the relevance
   check (which project, how it would help, strength of fit). On a
   quote-post, also read Brian's own added text for an explicit
   project target (see Routing).

5. Search again for topic matches (model names, paper titles, project
   names) in case the same idea is already filed under a different
   URL. Check existing survey, `research-backlog`, `rt-idea`, and
   `priority-1` issues, and familia#20 (its comments, child issues,
   and the short index in its body once that index exists).

6. Run the relevance check, then classify (Decision rules). Prefer,
   in order:
   (a) leave out only if no project relevance can be confirmed, with
       that reason in the run report (no GitHub write required);
   (b) a signed source-only comment on an existing matching issue
       (new source URL and/or a verified fact; no review);
   (c) add the item as a source row on an existing survey or catalog
       issue (same source-only exception, no review);
   (d) propose a new survey or research-backlog issue only when no
       existing issue fits, and file it after two independent
       reviews. For a survey issue, also pick the fitting
       subcategory: `survey:models`, `survey:research`,
       `survey:skills`, `survey:mct`, or `survey:application`;
   (e) write an idea card and send it for three reviews when the item
       is a concrete experiment or design that would become an
       `rt-idea`;
   (f) file a `priority-1` integration issue only when Brian has
       asked for that track. Do not mint a P1 on the on-demand path
       otherwise.

7. Apply the review gate before opening a new issue (three approvals
   for `rt-idea`, two for every other new issue). Do not apply that
   gate to left-out notes or to source-only comments on existing
   issues.

8. File or comment using the templates below. Every public issue or
   comment must include the source URL, author, date (PT), interaction
   type, a short summary, the relevance check, proposed labels, and a
   signature that names the agent and its role. New issues also carry
   the reviews that passed the gate. When a batch is filed, update
   familia#20's short body index with links to the new comments and
   child issues only, not every post. If #20's body still has the old
   empty table, replace it with that index when the first batch under
   this skill is filed, then update the index only when a later batch
   is filed.

9. Write a short run report for Brian only when something was filed,
   a review is waiting, a gap or failure occurred, or he asked for
   the run. Do not send a check-in that merely repeats what is already
   on GitHub.

## Decision rules

### Relevance check

For each interaction, confirm its relative relevance to a Brian
project before deciding what to file. Record all three:

- Which project (or which two, with a primary)
- How it would help that project
- Strength of fit: strong, plausible, or unconfirmed

When Brian's own added text on a quote-post names one of his
projects (for example "for <repo>", "for brianreborn/<repo>",
"for https://github.com/brianreborn/<repo>", "-> <repo>",
"#<repo>", or similar phrasing), treat that as a strong, explicit
relevance assertion. Relevance is confirmed and fit is strong; you
do not need to argue the fit. Route to that repo per the explicit
QRT target rule in Routing. This applies only to Brian's added QRT
text, not to the original post, and not to a bare retweet,
bookmark, or like.

Integrate anything with a plausible or strong fit. Do not leave an
item out because of its topic. Only leave out an item when no project
relevance can be confirmed, and record that reason in the run report.

If the only content is in an unread image, say that the image was not
read and do not guess. Relevance stays unconfirmed until the image is
read.

Items with no confirmed relevance do not need a GitHub comment and
are not listed one-by-one on familia#20. If a batch comment summarizes
them, the #20 index links that comment, not each item.

Hard safety limits (no exploit or attack procedures, no secrets) are
in Guardrails. They restrict what may be written, not which topics
may be considered. A relevant item can still be integrated at a safe
level of detail.

### Classification buckets

Use the familia#20 buckets, exactly one per interaction:

1. No confirmed project relevance -- leave out; record the reason.
2. Integrate as a model -- a model or runtime to catalog or test.
3. Integrate its design, but not in this project's repo -- belongs in
   another repo.
4. Integrate its design completely in the target project.

A post can also be tagged for later look-in without becoming an
implementation issue: that is the survey / research-backlog path, not
a fifth bucket. Record the bucket even when the filing is a survey
item.

When the filing is a survey issue, add `survey` and the most specific
subcategory (one-line definitions are also in Labels and the survey
template):

- `survey:models` -- models or engines to look into
- `survey:research` -- AGI research (not a working draft)
- `survey:skills` -- bundle-ready agent skills or skill sets
- `survey:mct` -- MCT-related items to look into
- `survey:application` -- standalone applications that run on the
  full agentic system (built on top of the swarm, not core
  components)

`@BrianReborn_alt` retweets, quotes, bookmarks, and likes are the
usual source of bucket 2 (new models and engines). Still scan
`@born_brian85001` every run; product ideas appear on both.

### Match against existing issues and markdown

An interaction matches an existing record when any of these hold:

- An issue body, comment, or in-repo `.md` file already cites the
  same post id.
- That record already cites the original (referenced) post, and this
  item is a retweet, quote, bookmark, or like of that original.
- The title and core idea are the same project action (same model,
  same paper, same mechanism) even if the new interaction is a
  different URL.

familia#20's body is a short index of comment links and child-issue
links, updated only when a batch is filed. It is not a post-by-post
ledger. Search #20's comments and those child issues for post ids;
do not expect the #20 body itself to cite every post.

On a match: comment, do not open a second issue. A signed comment
that only adds a source URL (with type and date) or a verified fact
needs no review. If the existing issue is a broad survey, add a
checklist row rather than a new issue (also source-only, no review).

Do not use a comment to bypass the new-issue review gates. A comment
that proposes a new experiment, changes scope, or otherwise is not
just a source or a verified fact is not a source-only comment. If
that work needs its own issue, write a card and use the two- or
three-review path.

If a later card passes three reviews and is a narrower experiment of
a broader `research-backlog` issue, file the `rt-idea` and link both
ways rather than silently replacing the older issue.

Do not comment on frozen issues (see Process limits). If the only
match is a frozen issue, note that in the run report and, if the idea
still needs a home, ask Brian or file on a non-frozen issue that can
hold the reference (after the matching review gate, if it is a new
issue).

### Routing (which repo)

When Brian's own added text on a quote-post names one of his
projects with phrasing such as "for <repo>", "for brianreborn/<repo>",
"for https://github.com/brianreborn/<repo>", "-> <repo>", "#<repo>",
or similar, that name is a strong, explicit routing instruction:

1. Treat relevance as confirmed and fit as strong (see Relevance
   check). Do not leave the item out for lack of fit.
2. Route the filing to exactly that repository. This overrides the
   inferred routing table below, including the usual HVVRAM-to-
   angel-freebsd default, when Brian named a different repo.
3. Resolve the name to an actual `brianreborn` repository before
   filing. Accept short names, documented aliases, and full GitHub
   URLs, case-insensitively, and verify that the resolved repo
   exists (read-only). Documented aliases in this skill include
   HVVRAM -> `brianreborn/angel-freebsd`. If the name is ambiguous,
   does not exist, and is not a documented alias, do not guess;
   ask Brian and wait for his answer.
4. If the QRT names more than one repo, the primary is the first
   named; file there and cross-link the others in the body. Do not
   open duplicates in each.
5. Dedup and the normal review gate for new issues still apply. An
   explicit target does not authorize a second issue for a post
   already on record, and it does not skip two- or three-review
   filing.
6. Record in the filed issue or comment, and on the card:
   `Routed by explicit QRT target: <owner/repo>`
   using the resolved repository name.

If there is no explicit QRT target, choose the repo by where the
work would land, using the table below. Familia is not the default
catch-all. File on familia only when the work is actually familia's
(graph, catalog, fleet, hermes, routing, installer, or
local-inference integration). If no project is a clear fit, stop and
ask Brian rather than defaulting to familia.

- `brianreborn/code-bootstraps-llama.cpp` -- llama.cpp pin, patches,
  serve flags, bootstrap layout, alternative runtimes next to the pin.
- `brianreborn/green-roomz` -- agent fleet, gateway, sandbox, headless
  browser, worktree/claims, live agent-status console.
- `brianreborn/green-agentz` -- agent memory, bundled skills,
  green-zkillz, provenance store.
- `brianreborn/angel-freebsd` -- FreeBSD port, RCTL/RACCT, work that
  is specifically for a FreeBSD desktop host, and HVVRAM.
- `brianreborn/meshforge` -- MeshForge-specific work.
- `brianreborn/papers` -- manuscript or paper-source collection, not
  product implementation.

HVVRAM does not go in familia. There is no dedicated HVVRAM
repository; the public experiment track is on
`brianreborn/angel-freebsd`. Route HVVRAM ideas there, unless a
dedicated HVVRAM repo is created later, in which case prefer that
repo and link the angel-freebsd track. Do not add new HVVRAM work
to familia. When refining older familia HVVRAM issues, prefer
commenting on or linking from the angel-freebsd track.

If two repos are reasonable, file in the primary one and link the
other in the body. Do not open duplicates in both. An explicit QRT
target already decides the primary; do not second-guess it.

### Review gates for new issues

- A new issue labeled `rt-idea` needs three independent approvals
  before it is opened.
- Every other new issue (survey, research-backlog, and similar) needs
  two independent approvals before it is opened.
- A signed source-only comment on an existing issue (source URL
  and/or a verified fact only) needs no review.
- Left-out notes in the run report (no confirmed relevance) need no
  review and no GitHub write.
- Do not mint a new `priority-1` issue unless Brian asks. If he asks
  to file one, file it as he asked; his request is the authorization.
  A promotion or label change to `priority-1` also needs his ask.

A promotion to `rt-idea` does not by itself authorize implementation,
installs on hosts, branches, pushes, or merges. Passing the review
gate only files or promotes the issue. Pickup for work is intended
to happen under `DESIGN.md`, and only with the explicit approval of
an administrator. Intake never schedules or starts that work itself.

## Review gate

Independent means different reviewers (different roles or people),
not two or three notes from the same reviewer.

- A signed review comment counts. The signature must identify the
  reviewer and the role.
- Valid verdicts: APPROVE, APPROVE with stated conditions, or
  CHANGES-NEEDED (or equivalent reject). Conditions travel into the
  issue body when the card is promoted.
- CHANGES-NEEDED blocks filing. Revise the card and resubmit to the
  reviewer who requested changes.
- For a two-review issue, one reject parks the card; do not file it.
- For an `rt-idea`, one reject with two approvals parks the card; do
  not file it.
- Reviews may live on the card file, in a review board file, or as
  signed comments once an issue exists. For a new issue, the required
  approvals must exist before the issue is opened.
- Suggested reviewer mix: someone who can check facts, someone who
  can check implementation effort, and, when a third review is
  required or the topic needs one, a specialist (platform,
  race/concurrency, or boundary/credentials). This skill does not
  name particular agents.

A card or issue that has passed this gate is eligible to be picked
up for work under `DESIGN.md` only after an administrator gives
explicit approval. This skill does not schedule or start that work.

Card (pre-issue) contents, minimum:

- Source URL (Brian's RT, QRT, bookmark, or like target) and, when
  different, the original post URL, plus author
- Date of the source interaction, in PT
- Interaction type: retweet, quote, bookmark, or like
- Short quote or paraphrase, clearly attributed
- Core idea in plain language
- Relevance: which project, how it would help, strength of fit
- When an explicit QRT target applied: Routed by explicit QRT
  target: <owner/repo>
- Rough effort and risk
- A first experiment, or "design study only", or "survey / look-in
  only" for a two-review issue
- Reviews section, starting at 0/2 or 0/3 as appropriate
- No invented measurements, repo facts, or licenses. Tag claims as
  "post says", "README says", or "verified".

## Templates

Use ASCII only in issues and comments. Prefer
`https://x.com/<handle>/status/<id>` when the handle is known; always
include the numeric id. Treat `https://x.com/i/status/<id>` (and the
twitter.com forms) as the same post.

When an explicit QRT target applied, include this line after the
Relevance block, using the resolved repository name:

    Routed by explicit QRT target: <owner/repo>

Omit that line when the rule did not apply.

### Source-only comment on an existing issue (no review)

    Source: https://x.com/<handle>/status/<id>
    Author: @<author>
    Date: <YYYY-MM-DD HH:MM PT>
    Type: retweet | quote | bookmark | like
    Account: @<brian handle that interacted>

    Summary: <one or two sentences>

    Relevance: project=<repo or project>; how it helps=<short>;
    fit=strong|plausible
    Why it belongs here: <one or two sentences>
    Routed by explicit QRT target: <owner/repo>
    Proposed labels: <existing labels, or none>

    -- <agent name> (<role>), <YYYY-MM-DD PT>

If the comment is only that source citation and/or a verified fact,
it may be posted without waiting for reviews. Do not add a new plan
or experiment in this comment.

### New survey or research-backlog issue (after 2/2)

Title: `Survey: <topic>` or `Research: <topic>`

    Filed after two independent reviewer approvals. Look-in or
    research only unless the body says otherwise.

    Source: https://x.com/<handle>/status/<id>
    Author: @<author>
    Date: <YYYY-MM-DD HH:MM PT>
    Type: retweet | quote | bookmark | like
    Account: @<brian handle that interacted>

    Summary: <short>

    Relevance: project=<repo or project>; how it helps=<short>;
    fit=strong|plausible
    Routed by explicit QRT target: <owner/repo>
    Proposed priority/labels: survey / survey:models | survey:research |
    survey:skills | survey:mct | survey:application, or
    research-backlog

    Claims in the post are unverified unless marked otherwise.

    Then the reviews and any conditions.

    -- <agent name> (<role>), <YYYY-MM-DD PT>

Survey subcategory meanings: `survey:models` (models or engines to
look into); `survey:research` (AGI research, not a working draft);
`survey:skills` (bundle-ready agent skills or skill sets);
`survey:mct` (MCT-related items to look into);
`survey:application` (standalone applications that run on the full
agentic system, built on top of the swarm, not core components).
Apply a subcategory only if that label already exists on the target
repo; do not create labels as part of this process.

If several interactions in the same request are one theme, one
aggregate issue is better than one issue per post. The body must still
list every source URL, author, date, and type. Do not point at a
private note in place of those URLs.

### New rt-idea issue (after 3/3)

Title: `rt-idea: <short name> (research only)`

Label: `rt-idea` (create it only if that repo already has it, or Brian
has approved adding it).

    Promoted after three independent reviewer approvals. Research only:
    this does not authorize installs on hosts, branches, pushes,
    or merges.

    Source (Brian's RT, QRT, bookmark, or like): https://x.com/<handle>/status/<id>
    Original post (if different): https://x.com/<author>/status/<id>
    Date: <YYYY-MM-DD PT>
    Type: retweet | quote | bookmark | like
    Relevance: project=<repo or project>; how it helps=<short>;
    fit=strong|plausible
    Routed by explicit QRT target: <owner/repo>
    Related issues: <links or "none">

    Then the card text, including every review and its conditions.

    -- <agent name> (<role>), <YYYY-MM-DD PT>

Do not cite a box-only path such as `/workspace/...` as the only copy
of the card. Paste the card text, or link a location that reviewers
can actually open (an issue or an in-repo `.md` file).

## Outputs

Each requested run produces:

- Zero or more signed issue comments, survey rows, or new issues,
  which together with existing issues and in-repo `.md` files remain
  the canonical record.
- Zero or more new or updated idea cards, with review status, until
  they are pasted into an issue or an in-repo `.md` file.
- A run report: what was requested, counts per account (fetched,
  left out for no confirmed relevance, matched, filed, cards opened,
  promotions), how "new" was determined, gaps, and failures. Send the
  report to Brian only under the rule in step 9.

This run does not schedule or start work. Vetted issues that have
passed the review gate are intended to be picked up for work under
`DESIGN.md`, and only with the explicit approval of an
administrator.

## Rate limits

- Respect the published limits of the X read capability. If they are
  unknown, page slowly, checkpoint after each page, and stop on
  repeated rate-limit errors.
- Do not retry authentication failures, login cooldowns, or empty
  tool connections in a loop.
- Search the issue tracker and repo markdown in batches (one query
  per repo or topic), not one request per post if a combined search
  will do.
- Offload classification and summarization to local models when
  possible.

## Audit trail

The issue tracker and in-repo markdown are the audit trail. Every
public GitHub write must be signed with agent name and role. Every
number, license, or repo fact in a card or issue must say whether it
is from the post, from a README, or verified. Every filed item must
cite its source post id in public text, so later runs can find it.

## Failure handling

- Partial X results: keep the interactions that arrived, mark missing
  ids as incomplete in the run report, and do not treat the walk as
  finished.
- Image-only or unread media: record the gap; do not invent the
  contents; leave relevance unconfirmed until the image is read.
- Issue-tracker write failure: keep a drafted comment or issue text
  only long enough to retry, after a search that proves it was not
  actually created.
- Disagreement between this skill and a live issue or in-repo `.md`
  file: follow the live record, note the inconsistency in the run
  report.
- Outage of the X read capability, or of the authenticated bookmark
  and like read: stop. Do not switch to a write-capable session or an
  ad-hoc scrape. RTs and QRTs may still be collected if a read-only
  public listing works; do not invent bookmarks or likes.

## Process limits

- X writes are off. No posts, replies, likes, unlikes, reposts,
  follows, DMs, mass posting, or bookmark management (no creating,
  deleting, or organizing bookmarks). Any X write is a separate
  action and needs Brian's explicit OK for that action. Likes and
  bookmarks are collected by reading existing ones, not by creating
  them.
- Never sign in as `@born_brian85001` or `@BrianReborn_alt` except
  insofar as a read-only authenticated session is required to list
  bookmarks and likes. Do not use that session to write.
- New branches, pull requests, and pushes need Brian's OK. This skill
  never opens them as part of intake.
- Do not send Brian a check-in or FYI that only repeats what is already
  on a GitHub issue or pull request, unless the message is needed to
  get another agent to act or he asked for the run.
- Agents may post signed comments that unambiguously identify the
  agent name and role. Pushes still need a per-push OK.
- Frozen hot files and issues must not be touched: familia issues
  #327-#331; `familia_home.sh`, `proto_chat.sh`, `open_ui.sh`,
  `ui_bridge.py`, menus, `graph.yaml`, and the FreeBSD/Termux docs.
  Leave the `open_ui.sh` lint failure on main alone.
- Do not propose restarts of model servers or resident models, and
  do not reboot hosts of any archetype, as part of this process.
- ASCII only in this document and in GitHub issue text. No Unicode
  decoration.
- Offload what you can to local models.

## Guardrails

These are hard safety limits on what may be written, not topic bans.

- No exploits, exploit proofs of concept, or attack procedures.
- Do not put secrets in issues. Security findings that belong in
  public issues still omit token values, keys, and credentials.
- Do not invent evidence, measurements, licenses, or credentials.

## Labels (familia)

Use existing labels; do not invent parallels. Do not create labels
as part of this process. If a listed label is not yet on the target
repo, do not apply or mint it; use a parent label that does exist
(for example `survey`) and note the gap in the run report.

- `rt-idea` -- idea promoted after three independent reviews
- `survey` -- look-in collection of in-scope X interactions
- `survey:models` -- models or engines to look into
- `survey:research` -- AGI research (not a working draft)
- `survey:skills` -- bundle-ready agent skills or skill sets
- `survey:mct` -- MCT-related items to look into
- `survey:application` -- standalone applications that run on the
  full agentic system (built on top of the swarm, not core
  components)
- `research-backlog` -- research ideas from reposts, not a sprint
- `priority-1` -- required feature or test target; do not apply on
  the on-demand path unless Brian asks
- `priority-0`, `priority:top` -- only if Brian sets that priority
- `duplicate` -- if a second issue was opened by mistake

Other routing repos may have only `rt-idea` among these. Do not
require familia-only labels elsewhere.
