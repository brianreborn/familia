# Offline queue (Android / Termux) — issue #332

When SSH or Wi-Fi to the fleet drops on an Android/Termux host, queue commands
locally; when connectivity returns, post them as GitHub issue comments and pull
replies back.

## Operator-run only

`probe`, `enqueue`, `status`, `flush`, `pull`, and `sync` are **operator-run
only**. Do **not** wire auto-enqueue into `proto_chat.sh`, `familia_home.sh`, or
other launchers. If a launcher hook is wanted later, add it as an explicit
opt-in after the Antigravity sprint — never silently.

## Default issue

The default GitHub issue is **#332**. Override with:

- `--issue N` on `enqueue`, or
- `FAMILIA_OFFLINE_ISSUE=N`

`N` must be a positive integer.

## Sync

```bash
python3 scripts/offline_queue.py sync
```

Operator runs this when ready to flush the local queue and pull replies. There
is no background daemon and no proto_chat integration in this change.

## Replies

A later issue comment counts as a reply **only if it quotes our marker**
(`familia-offline-queue:id=<uuid>` or the bare entry id). Other later comments
on the issue are ignored.

## Menu

The `scripts/menu-internal.txt` row is deferred to Antigravity (their file).
Until then the coverage test allow-lists this CLI like `sec_assess`.

## State / privacy

Queue and probe state live under `$XDG_STATE_HOME/familia/offline` (fallback
`$HOME/.local/state/familia/offline`). Dirs `0700`, files `0600`, symlink
refusing, flock. Host/port come from env only — no hostnames in the repo.

## Limits and safety

- **Repo:** `FAMILIA_OFFLINE_REPO` / `--repo` must be `owner/name` with GitHub-allowed
  characters, no `..`, and no leading `.` or `-` (owner ≤39, name ≤100).
- **Body size:** queued and flushed payloads are capped by `FAMILIA_OFFLINE_MAX_BODY`
  (default 32768 bytes). Enqueue refuses oversize bodies; flush truncates any
  already-queued oversize body and appends `[truncated:FAMILIA_OFFLINE_MAX_BODY]`.
- **GitHub REST:** the `Authorization` header is unredirected. Cross-host or
  scheme-changing redirects drop auth; non-https redirects are refused.
- **Public issue:** flushed command text is posted to the configured issue (default
  #332) after scrubbing IPs, ports, emails, tokens and private-looking hostnames.
