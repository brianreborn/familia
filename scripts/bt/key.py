#!/usr/bin/env python3
"""REQ-REPO-02 key <-> magnet URI.  key.py KEY TRACKER_URL -> prints: <magnet-uri>\t<path-inside-torrent>"""
import sys, urllib.parse
def parse(key):
    if not key.startswith("magnet:urn:btih:"): raise SystemExit(f"key: expected magnet:urn:btih:<hex>:<path>, got {key!r}")
    rest = key[len("magnet:urn:btih:"):]; ih, _, path = rest.partition(":")
    if len(ih) != 40 or not path: raise SystemExit(f"key: bad key {key!r}")
    return ih.lower(), path
if __name__ == "__main__":
    ih, path = parse(sys.argv[1])
    print(f"magnet:?xt=urn:btih:{ih}&dn={urllib.parse.quote(path)}&tr={urllib.parse.quote(sys.argv[2], safe='')}\t{path}")
