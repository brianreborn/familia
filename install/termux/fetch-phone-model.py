#!/usr/bin/env python3
"""Download a phone-tier GGUF pinned in graph.yaml; verify sha256; print absolute path.

Pins come from graph.yaml (sha256 + db id) and registry/models/<db>.json
(repo, revision, file). Never trust an unverified download. Offline re-run
reuses a local file whose sha256 already matches the pin.

Usage:
  python3 install/termux/fetch-phone-model.py [--model ID] [--prefix DIR]
                                              [--dry-run] [--json]
Env:
  FAMILIA_PHONE_MODEL   default model id when --model omitted
  FAMILIA_PREFIX        install root (default: $HOME/familia); models land in
                        $PREFIX/models/<filename>
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def die(msg: str, code: int = 1) -> None:
    print(f"fetch-phone-model: error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def say(msg: str) -> None:
    print(f"fetch-phone-model: {msg}", file=sys.stderr)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_yaml(path: str):
    try:
        import yaml  # type: ignore
    except ImportError:
        die("pyyaml required to read graph.yaml (pip install pyyaml)")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_model(model_id: str) -> dict:
    graph_path = os.path.join(ROOT, "graph.yaml")
    if not os.path.isfile(graph_path):
        die(f"missing {graph_path}")
    graph = load_yaml(graph_path)
    models = graph.get("models") or {}
    if model_id not in models:
        die(f"model id {model_id!r} not in graph.yaml")
    entry = models[model_id]
    want_sha = (entry.get("sha256") or "").strip().lower()
    db = entry.get("db")
    if not want_sha or not db:
        die(f"graph model {model_id!r} missing sha256 or db pin")
    reg_path = os.path.join(ROOT, "registry", "models", f"{db}.json")
    if not os.path.isfile(reg_path):
        die(f"missing registry entry {reg_path}")
    reg = json.load(open(reg_path, encoding="utf-8"))
    repo = reg.get("repo")
    rev = reg.get("revision")
    fname = reg.get("file")
    if not repo or not rev or not fname:
        die(f"registry {db} missing repo/revision/file")
    url = f"https://huggingface.co/{repo}/resolve/{rev}/{fname}"
    return {
        "model_id": model_id,
        "db": db,
        "sha256": want_sha,
        "repo": repo,
        "revision": rev,
        "file": fname,
        "url": url,
    }


def download(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".partial"
    req = urllib.request.Request(url, headers={"User-Agent": "familia-fetch-phone-model/1"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except urllib.error.URLError as e:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        die(f"download failed: {url}: {e}")
    os.replace(tmp, dest)


def main(argv: list[str]) -> int:
    model_id = os.environ.get("FAMILIA_PHONE_MODEL", "").strip()
    prefix = os.environ.get("FAMILIA_PREFIX", os.path.join(os.path.expanduser("~"), "familia"))
    dry = False
    as_json = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        if a == "--dry-run":
            dry = True
        elif a == "--json":
            as_json = True
        elif a == "--model" and i + 1 < len(argv):
            model_id = argv[i + 1]
            i += 1
        elif a == "--prefix" and i + 1 < len(argv):
            prefix = argv[i + 1]
            i += 1
        else:
            die(f"unknown option {a!r}", 2)
        i += 1
    if not model_id:
        die("pass --model ID or set FAMILIA_PHONE_MODEL")

    info = resolve_model(model_id)
    dest = os.path.join(prefix, "models", info["file"])
    info["path"] = dest

    if os.path.isfile(dest):
        got = sha256_file(dest)
        if got.lower() == info["sha256"]:
            say(f"cached verified {dest} (sha256 ok; offline ok)")
            if as_json:
                print(json.dumps(info, indent=2))
            else:
                print(dest)
            return 0
        say(f"cached file sha mismatch (got {got}, want {info['sha256']}); re-download")

    if dry:
        say(f"[dry-run] would download {info['url']} -> {dest}")
        say(f"[dry-run] would verify sha256 {info['sha256']}")
        if as_json:
            print(json.dumps(info, indent=2))
        else:
            print(dest)
        return 0

    say(f"download {info['file']} from {info['repo']}@{info['revision'][:12]}")
    download(info["url"], dest)
    got = sha256_file(dest)
    if got.lower() != info["sha256"]:
        try:
            os.remove(dest)
        except OSError:
            pass
        die(f"sha256 mismatch for {info['file']}: got {got} want {info['sha256']}")
    say(f"sha256 ok ({got})")
    if as_json:
        print(json.dumps(info, indent=2))
    else:
        print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
