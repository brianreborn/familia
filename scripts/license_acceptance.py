#!/usr/bin/env python3
"""Per-license, version-sensitive consent records shared by license gates."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent


def accepted_dir(legacy_file=None):
    override = os.environ.get("FAMILIA_ACCEPTED_LICENSES_DIR")
    if override:
        return Path(override).expanduser()
    legacy = (legacy_file or os.environ.get("FAMILIA_LICENSE_ACCEPT_FILE")
              or os.environ.get("FAMILIA_MODEL_LICENSE_ACCEPT_FILE"))
    if legacy:
        return Path(legacy).expanduser().parent / "accepted-licenses"
    if sys.platform == "win32":
        state = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state).expanduser() / "familia" / "accepted-licenses"


def _hash(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evidence(item):
    parts = []
    for value in [item.get("text")] + list(item.get("extra_text") or []):
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            parts.append({"sha256": digest})
        else:
            parts.append({"text": str(value)})
    if item.get("evidence_sha256"):
        parts.append({"sha256": item["evidence_sha256"]})
    if item.get("excerpts"):
        parts.append({"excerpts": item["excerpts"]})
    if not parts:
        parts.append({"source": item.get("source"), "link": item.get("link")})
    return _hash(parts)


def evidence_sha256(text=None, extra_text=(), source=None, link=None, excerpts=None):
    return _evidence({
        "text": text, "extra_text": list(extra_text or ()), "source": source,
        "link": link, "excerpts": excerpts,
    })


def fingerprint(item):
    license_id = item.get("license") or "unknown"
    unknown = item.get("category") == "unknown" or license_id == "unknown"
    data = {"license": license_id, "license_version": item.get("version") or license_id,
            "evidence_sha256": item.get("evidence_sha256") or _evidence(item)}
    if unknown:
        data.update({"kind": item.get("kind"), "item_id": item.get("id"),
                     "source": item.get("source"), "link": item.get("link")})
    return _hash(data), data


def path_for(item, directory=None):
    digest, data = fingerprint(item)
    label = "unknown" if data["license"] == "unknown" else data["license"]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip(".-_").lower()[:48] or "license"
    return (Path(directory) if directory else accepted_dir()) / f"license-{slug}-{digest}.md"


def files_for(items, directory=None):
    return sorted({str(path_for(item, directory)) for item in items})


def is_accepted(item, directory=None):
    path = path_for(item, directory)
    try:
        record = json.loads(path.read_text(encoding="utf-8").split("```json\n", 1)[1].split("\n```", 1)[0])
    except (OSError, ValueError, IndexError):
        return False
    digest, _ = fingerprint(item)
    return record.get("fingerprint") == digest and (
        item.get("category") != "unknown" or record.get("accepted_unknown") is True
    )


def record(item, how, unknown_ok=False, directory=None):
    digest, data = fingerprint(item)
    unknown = item.get("category") == "unknown" or data["license"] == "unknown"
    if unknown and not unknown_ok:
        return None
    path = path_for(item, directory)
    if is_accepted(item, directory):
        return str(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record_data = {
        "fingerprint": digest,
        "license": data["license"],
        "license_version": data["license_version"],
        "evidence_sha256": data["evidence_sha256"],
        "accepted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "accepted_by": how,
        "item": {"kind": item.get("kind"), "id": item.get("id")},
        "source": item.get("source"),
        "link": item.get("link"),
        "accepted_unknown": bool(unknown and unknown_ok),
    }
    body = "# Familia license acceptance\n\n```json\n%s\n```\n" % json.dumps(
        record_data, indent=2, sort_keys=True, ensure_ascii=True
    )
    fd, temp = tempfile.mkstemp(prefix=".accepted-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(path)
