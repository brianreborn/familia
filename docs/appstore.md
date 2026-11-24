# App store

The familia app store is a plain display of tweets that promote apps. Each card
puts the app first (name, one-line pitch, link, platform), with the tweet text,
author and date below. Nothing fancy: two front ends over one data file.

| View | Run | What you get |
|---|---|---|
| gum (terminal) | `sh scripts/appstore.sh` (home menu: App store -> browse) | ASCII-art banner, pick a platform with `gum choose`, scroll bordered cards in `gum pager`, pick an app with `gum filter` to open its link. No gum or no TTY: the same cards as plain ASCII text (`--print`). |
| HTML | `python3 scripts/appstore.py html` (home menu: App store -> web page) | One static page in the cockpit colors (dark panels, cyan edges, green title, gold pitch) with a card grid and platform chips. No frameworks, no CDN, no remote loads (a CSP meta tag enforces it). Written to `$XDG_CACHE_HOME/familia/appstore/index.html` with its media copied beside it. |

## Data (ships with the release)

The data is rolled into the release package, not fetched at run time:

```
appstore/data/feed.json      feed document (below)
appstore/data/media/         images and video the feed points at
appstore/data/SHA256SUMS     sha256 of every file above
```

`scripts/build_appimage.sh` copies the tree into the AppImage and refuses to
pack when `appstore/data` is missing or `SHA256SUMS` does not match. After
editing the data, run `python3 scripts/appstore.py checksums --write`.

Lookup order: `--data DIR` / `FAMILIA_APPSTORE_DATA`, then the installed
release copy (`$FAMILIA_APPDIR/usr/share/familia/appstore/data`, set by the
AppImage), then this tree's `appstore/data`. A release feed with no items falls
back to the example fixture `examples/appstore/feed.sample.json`. Every handle,
app and link in that fixture is made up.

```json
{
  "format": "familia-appstore-feed",
  "version": 1,
  "items": [
    {
      "app_name": "PaperNote (example)",
      "app_pitch": "Offline-first notes that live in one plain file.",
      "app_link": "https://example.com/papernote",
      "platform": "Android",
      "author_handle": "example_dev_one",
      "author_name": "Example Dev One",
      "text": "Shipped v1 of my offline notes app today.",
      "date": "2026-11-20T17:04:00Z",
      "url": "https://x.com/example_dev_one/status/1000000000000000001",
      "media": [{"type": "image", "path": "media/papernote.svg", "alt": "icon"}]
    }
  ]
}
```

Rules the loader enforces: every field above except `media` is required; links
must be `http(s)://` (anything else is dropped); media paths must be relative to
the data dir (no URL, no absolute path, no `..`), and `type` is `image` or
`video`. Terminal output strips escape and control characters; HTML output
escapes every field.

## Optional: refreshing the data from X

There is no live X fetch. Whoever prepares a release can collect tweets by
hand or with their own tools (for example the Agent-Reach path behind
`scripts/search_x.sh`), write them into `appstore/data/feed.json` in the format
above, put any images or video in `appstore/data/media/`, and run
`checksums --write`. `scripts/appstore.py` can also read a `.jsonl` export
(one item per line) through `load_feed_file` if you script the conversion.
