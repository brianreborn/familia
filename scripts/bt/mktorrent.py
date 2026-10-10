#!/usr/bin/env python3
"""Create a private single-file torrent for a model or KV slot-save file.

Prints the REQ-REPO-02 key  magnet:<xt>:<path-inside-torrent>
e.g. magnet:urn:btih:<40hex>:slot0.bin  and registers <hex>.torrent in --allow-dir.

  mktorrent.py FILE --announce http://192.168.1.9:6969/announce --out-dir DIR [--allow-dir DIR]
"""
import argparse, hashlib, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bencode import enc

def make(path, announce, piece=1 << 18):
    pieces = b""
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(piece), b""): pieces += hashlib.sha1(b).digest()
    info = {"name": os.path.basename(path), "length": os.path.getsize(path), "piece length": piece, "pieces": pieces, "private": 1}
    return enc({"announce": announce, "info": info, "created by": "familia transport-poc"}), hashlib.sha1(enc(info)).hexdigest()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--announce", required=True)
    ap.add_argument("--out-dir", required=True); ap.add_argument("--allow-dir"); o = ap.parse_args()
    data, ih = make(o.file, o.announce)
    os.makedirs(o.out_dir, exist_ok=True); t = os.path.join(o.out_dir, ih + ".torrent")
    open(t, "wb").write(data)
    if o.allow_dir: os.makedirs(o.allow_dir, exist_ok=True); shutil.copy(t, os.path.join(o.allow_dir, ih + ".torrent"))
    print(f"magnet:urn:btih:{ih}:{os.path.basename(o.file)}")

if __name__ == "__main__": main()
