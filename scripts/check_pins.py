#!/usr/bin/env python3
"""Validate and fetch every repository pin without credentials."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"[0-9a-f]{40}\Z")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
BAD_REV_PREFIX = "b1b770d"


class PinError(ValueError):
    pass


def parse_pins(text: str) -> list[dict[str, str]]:
    pins: list[dict[str, str]] = []
    names: set[str] = set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        columns = line.split("\t")
        # pins.txt also catalogs ontology values; those rows are not repositories.
        if columns[0] in ("node", "transport"):
            continue
        if len(columns) != 4:
            raise PinError(f"line {number}: expected name, revision, HTTPS origin, and role")
        name, revision, origin, role = (value.strip() for value in columns)
        if not NAME_RE.fullmatch(name):
            raise PinError(f"line {number}: invalid pin name {name!r}")
        if name in names:
            raise PinError(f"line {number}: duplicate pin name {name!r}")
        names.add(name)
        if revision.startswith(BAD_REV_PREFIX):
            raise PinError(f"line {number}: forbidden llama.cpp commit prefix {BAD_REV_PREFIX}")
        if not PIN_RE.fullmatch(revision):
            raise PinError(f"line {number}: revision must be a full lowercase 40-hex commit SHA")
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError as exc:
            raise PinError(f"line {number}: origin must be an HTTPS GitHub repository URL") from exc
        if (parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username
                or parsed.password or port not in (None, 443) or parsed.query or parsed.fragment
                or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", parsed.path)):
            raise PinError(f"line {number}: origin must be an HTTPS GitHub repository URL")
        if not role:
            raise PinError(f"line {number}: role must not be empty")
        pins.append({"name": name, "revision": revision, "origin": origin, "role": role})
    if not pins:
        raise PinError("pins.txt contains no repository pins")
    return pins


def run_git(repository: Path, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-c", "credential.helper=", "-C", str(repository), *args],
        text=True, capture_output=True, check=False, timeout=timeout, env=env,
    )


def is_ancestor(repository: Path, revision: str, ref: str) -> bool:
    result = run_git(repository, "merge-base", "--is-ancestor", revision, ref)
    return result.returncode == 0


def warn_if_fork_pin_is_branch_only(pin: dict[str, str], repository: Path) -> None:
    parsed = urlsplit(pin["origin"])
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if parsed.hostname != "github.com" or len(parts) != 2 or parts[0].lower() != "brianreborn":
        return
    owner, repo = parts
    request = Request(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "familia-pin-check"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            metadata = json.load(response)
        if metadata.get("fork") is not True:
            return
        default_branch = metadata["default_branch"]
        compare_url = (f"https://api.github.com/repos/{owner}/{repo}/compare/"
                       f"{quote(default_branch, safe='')}...{pin['revision']}")
        compare = Request(compare_url, headers={"Accept": "application/vnd.github+json",
                                                 "User-Agent": "familia-pin-check"})
        with urlopen(compare, timeout=15) as response:
            status = json.load(response).get("status")
        if status in ("behind", "identical"):
            return

        refs = run_git(repository, "fetch", "--quiet", "--unshallow", "--filter=blob:none", "origin",
                       "+refs/heads/*:refs/remotes/origin/*", "+refs/tags/*:refs/tags/*", timeout=300)
        if refs.returncode:
            print(f"WARNING {pin['name']}: fork branch/tag durability could not be checked")
            return
        tags = run_git(repository, "for-each-ref", f"--contains={pin['revision']}",
                       "--format=%(refname)", "refs/tags")
        if tags.returncode == 0 and tags.stdout.strip():
            return
        default_ref = f"refs/remotes/origin/{default_branch}"
        if is_ancestor(repository, pin["revision"], default_ref):
            return
        branches = run_git(repository, "for-each-ref", f"--contains={pin['revision']}",
                           "--format=%(refname)", "refs/remotes/origin")
        branch_only = [ref for ref in branches.stdout.splitlines()
                       if ref != default_ref and branches.returncode == 0]
        if branch_only:
            print(f"WARNING {pin['name']}: {pin['revision']} is reachable only from non-default fork branch(es) "
                  f"{', '.join(branch_only)} and no tag; deleting those refs would break the pin")
    except (HTTPError, URLError, TimeoutError, KeyError, ValueError, OSError, subprocess.TimeoutExpired):
        print(f"WARNING {pin['name']}: fork branch/tag durability lookup was unavailable")


def verify_pin(pin: dict[str, str], scratch: Path, index: int) -> None:
    repository = scratch / str(index)
    repository.mkdir()
    initialized = subprocess.run(["git", "init", "--bare", "--quiet", str(repository)],
                                 text=True, capture_output=True, check=False)
    if initialized.returncode:
        raise PinError(f"{pin['name']}: could not initialize temporary Git repository")
    remote = run_git(repository, "remote", "add", "origin", pin["origin"])
    if remote.returncode:
        raise PinError(f"{pin['name']}: could not set its HTTPS origin")
    fetched = run_git(repository, "fetch", "--quiet", "--no-tags", "--depth=1", "origin", pin["revision"])
    if fetched.returncode:
        detail = fetched.stderr.strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise PinError(f"{pin['name']}: pinned commit is not fetchable from its declared origin{suffix}")
    present = run_git(repository, "cat-file", "-e", f"{pin['revision']}^{{commit}}")
    if present.returncode:
        raise PinError(f"{pin['name']}: fetched object is not a commit")
    print(f"OK {pin['name']} {pin['revision']} exists at {pin['origin']}")
    warn_if_fork_pin_is_branch_only(pin, repository)


def main() -> int:
    try:
        pins = parse_pins((ROOT / "pins.txt").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="familia-pin-check-") as temp:
            scratch = Path(temp)
            for index, pin in enumerate(pins):
                verify_pin(pin, scratch, index)
    except (OSError, PinError, subprocess.TimeoutExpired) as exc:
        print(f"pin check failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified {len(pins)} repository pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
