---
name: x-research-projects
description: >-
  Use when asked to find projects, repos, or tools the user posted or reposted
  about on X (e.g. "what was that firewall repo I RTed", "find Hermes/MCP
  starters I shared", "list security tools from my posts"), and turn them into
  a short verified candidate table for the user to pick from.
---
# X research → project candidates

Placeholders, filled by the caller or routine (never hard-code them here):
`{MAIN_HANDLES}` the user's main accounts · `{READ_ALT}` the read-only alt
signed into the X connector · `{TOPIC_KEYWORDS}` the ask's keywords ·
`{START}`/`{END}` the date window.

## Steps

1. **Load the X guide first.** Read `x-api-mcp-guide` before any X call, and
   again on any X error. Use the X connector or built-in public reads only.
2. **Read through `{READ_ALT}` only.** Never sign in as a main account, in a
   browser or anywhere else, and never ask for or accept a token.
3. **Pace the calls.** Stay under about 30 requests/min, 1,000/day, and 25
   results per call. Keep expansions to what you use (`author_id`,
   `referenced_tweets.id`).
4. **Search reposts and quotes, then sweep the timeline.**
   `(from:{MAIN_HANDLE}) (is:retweet OR is:quote) ({TOPIC_KEYWORDS})` with
   `{START}`–`{END}`. Keyword filters miss reposts worded differently, so also
   do one unfiltered pass over each main's timeline in the window.
   Recent search covers 7 days; older needs full-archive, so count first.
5. **Treat empty search as unproven.** Search is the flakiest surface. Loosen
   keywords and widen the window, and check the timeline, before concluding
   "not found".
6. **Re-fetch every original by id.** Reposts truncate text and keep t.co
   links wrapped. Request `referenced_tweets`, `note_tweet`, `entities.urls`
   and use each expanded URL. Skip links back to the post's own media.
7. **Follow "link below" posts.** Run `conversation_id:{ID} from:{AUTHOR}`
   before deciding a post has no link. If the list is in an image, say so;
   don't guess its contents.
8. **Keep `data` from partial results.** On 200 + `errors[]`, skip the listed
   ids and mark those posts "original unavailable".
9. **Save as you go, privately.** Write raw results, queries, window, paging
   depth, and gaps (missing quotes, unread images) to a private working folder
   so later passes reuse them. Never put raw dumps or handles in a public repo.
10. **Dedupe to one candidate per project.** Key by repo URL (else by original
    post id), and log every post id that pointed to it. The count of separate
    posts is the signal, not the raw hit count. Drop drive-bys (link-only
    reposts, hype, unverifiable) into a one-line "skipped" note.
11. **Verify every GitHub link.** Check it resolves (no 404), note archived or
    stale repos (last commit date), license, and for MCP servers whether it
    runs as a local subprocess (stdio) or a remote proxy (HTTP/SSE).
12. **Tag claims by source.** "post says", "README says", or "verified (read
    the code or ran it)". Never promote a README tagline to fact.

## Output

A short table: name · one line · URL · why it fits · source tag · posts that
pointed to it. Then one recommended pick with a one-line reason, ranked by fit
to the ask, license, maintenance, and offline/self-hosted install. Keep "the
user reposted it" separate from "it's good".

**Stop at the pick.** Wait for the user's choice before opening an issue or
implementing anything.

## Don't

- Post, reply, like, repost, follow, bookmark, or DM, even from the alt. Any
  write is a separate action that needs the user's explicit OK.
- Sign in as a main account, or route around a connector failure via browser.
- Retry 401s, zero-tool connections, or login cooldowns in a loop.
- Propose a link nobody verified, or silently drop a dead one (mark it dead).
