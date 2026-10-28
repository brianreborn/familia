#!/usr/bin/env python3
"""refuse_soname_skew: fail closed before llama-server start when bin/lib packs disagree.

Platform seatbelt (docs/platform/gpu-path-layout.md). Race re-stats fingerprints
after PolicyGate / before screen attach (TOCTOU).

  FAMILIA_REFUSE_SONAME_SKEW  default on (unset / 1 / true / yes).
                              off: 0 / false / off / no

  python3 scripts/refuse_soname_skew.py --bin PATH   # JSON on stdout
  from refuse_soname_skew import refuse_soname_skew, fingerprint, env_enabled
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from typing import Callable, Iterable, List, Optional, Sequence

# Pack-owned sonames (llama.cpp shared builds). System libs (libc, libstdc++) ignored.
_PACK_SONAME = re.compile(r"^(libggml|libllama)([.-].*)?\.so(\..+)?$")

_OFF_VALUES = {"0", "false", "off", "no"}
_ON_VALUES = {"1", "true", "yes", "on"}


def env_enabled(environ=None) -> bool:
    """FAMILIA_REFUSE_SONAME_SKEW: unset or truthy → on; 0/false/off/no → off."""
    env = os.environ if environ is None else environ
    raw = env.get("FAMILIA_REFUSE_SONAME_SKEW")
    if raw is None or raw.strip() == "":
        return True
    v = raw.strip().lower()
    if v in _OFF_VALUES:
        return False
    if v in _ON_VALUES:
        return True
    # Unknown → fail closed (treat as on).
    return True


def is_pack_soname(name: str) -> bool:
    return bool(_PACK_SONAME.match(name))


def _dir_has_pack_sonames(d: str) -> bool:
    try:
        for name in os.listdir(d):
            if is_pack_soname(name) and os.path.isfile(os.path.join(d, name)):
                return True
    except OSError:
        pass
    return False


def pack_search_dirs(bin_path: str) -> List[str]:
    """dirname(bin), optional dirname(bin)/lib, and dirname(bin)/../lib for bin/ layouts.

    Sibling `../lib` is included when the binary lives in a directory named `bin`
    (Termux grz-runtime/bin + lib) or when that lib dir already holds pack sonames.
    Avoids treating e.g. /usr/lib as a pack root for a stray binary under /tmp.
    """
    bin_dir = os.path.dirname(os.path.realpath(bin_path))
    out: List[str] = []
    seen = set()

    def add(d: str) -> None:
        if not d or not os.path.isdir(d):
            return
        rp = os.path.realpath(d)
        if rp in seen:
            return
        seen.add(rp)
        out.append(rp)

    add(bin_dir)
    add(os.path.join(bin_dir, "lib"))
    parent_lib = os.path.join(os.path.dirname(bin_dir), "lib")
    if os.path.isdir(parent_lib):
        if os.path.basename(bin_dir) == "bin" or _dir_has_pack_sonames(parent_lib):
            add(parent_lib)
    return out


def _read_cstr(data: bytes, off: int) -> str:
    end = data.find(b"\x00", off)
    if end < 0:
        end = len(data)
    return data[off:end].decode("utf-8", "replace")


def read_needed_elf(path: str) -> List[str]:
    """Pure-Python DT_NEEDED list from an ELF binary. Raises ValueError if not ELF."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError(f"{path}: not ELF")
    ei_class, ei_data = data[4], data[5]
    if ei_data not in (1, 2):
        raise ValueError(f"{path}: unknown ELF endianness")
    endian = "<" if ei_data == 1 else ">"
    if ei_class == 2:  # ELF64
        e_phoff = struct.unpack_from(endian + "Q", data, 32)[0]
        e_phentsize, e_phnum = struct.unpack_from(endian + "HH", data, 54)
        ph_fmt = endian + "IIQQQQQQ"
        ph_size = struct.calcsize(ph_fmt)
        dyn_tag_fmt = endian + "QQ"
    elif ei_class == 1:  # ELF32
        e_phoff = struct.unpack_from(endian + "I", data, 28)[0]
        e_phentsize, e_phnum = struct.unpack_from(endian + "HH", data, 42)
        ph_fmt = endian + "IIIIIIII"
        ph_size = struct.calcsize(ph_fmt)
        dyn_tag_fmt = endian + "II"
    else:
        raise ValueError(f"{path}: unknown ELF class {ei_class}")

    dyn = None  # (file_off, filesz, vaddr)
    loads = []  # (vaddr, filesz, file_off)
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        if o + ph_size > len(data):
            break
        fields = struct.unpack_from(ph_fmt, data, o)
        if ei_class == 2:
            p_type, _p_flags, p_offset, p_vaddr, _p_paddr, p_filesz, _p_memsz, _p_align = fields
        else:
            p_type, p_offset, p_vaddr, _p_paddr, p_filesz, _p_memsz, _p_flags, _p_align = fields
        if p_type == 1:  # PT_LOAD
            loads.append((p_vaddr, p_filesz, p_offset))
        elif p_type == 2:  # PT_DYNAMIC
            dyn = (p_offset, p_filesz, p_vaddr)

    if dyn is None:
        return []

    def vaddr_to_file(vaddr: int) -> Optional[int]:
        for v, fsz, fo in loads:
            if v <= vaddr < v + fsz:
                return fo + (vaddr - v)
        return None

    dyn_off, dyn_fsz, _ = dyn
    tag_size = struct.calcsize(dyn_tag_fmt)
    strtab_vaddr = None
    needed_offs: List[int] = []
    i = 0
    while i + tag_size <= dyn_fsz:
        tag, val = struct.unpack_from(dyn_tag_fmt, data, dyn_off + i)
        i += tag_size
        if tag == 0:
            break
        if tag == 5:  # DT_STRTAB
            strtab_vaddr = val
        elif tag == 1:  # DT_NEEDED
            needed_offs.append(val)

    if strtab_vaddr is None:
        return []
    strtab_off = vaddr_to_file(strtab_vaddr)
    if strtab_off is None:
        # Some binaries store STRTAB as file offset when vaddr mapping fails; try direct.
        if strtab_vaddr < len(data):
            strtab_off = strtab_vaddr
        else:
            return []
    return [_read_cstr(data, strtab_off + n) for n in needed_offs]


def read_needed(path: str, *, needed_fn: Optional[Callable[[str], Sequence[str]]] = None) -> List[str]:
    if needed_fn is not None:
        return list(needed_fn(path))
    return read_needed_elf(path)


def find_in_dirs(soname: str, dirs: Sequence[str]) -> List[str]:
    """All realpaths of soname under dirs (may be more than one when bin+lib disagree)."""
    found = []
    seen = set()
    for d in dirs:
        p = os.path.join(d, soname)
        if os.path.isfile(p) or os.path.islink(p):
            try:
                rp = os.path.realpath(p)
            except OSError:
                continue
            if rp not in seen and os.path.isfile(rp):
                seen.add(rp)
                found.append(rp)
    return found


def _file_id(path: str) -> dict:
    """Cheap stat identity for TOCTOU re-check (inode/mtime/size/dev)."""
    try:
        st = os.stat(path)
    except OSError as e:
        return {"path": path, "error": str(e)}
    return {
        "path": path,
        "ino": st.st_ino,
        "dev": st.st_dev,
        "size": st.st_size,
        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        "mode": st.st_mode,
    }


def fingerprint(
    bin_path: str,
    *,
    needed_fn: Optional[Callable[[str], Sequence[str]]] = None,
    lib_paths: Optional[Sequence[str]] = None,
) -> dict:
    """Stat bin + key pack libs. Cheap to call twice (Race TOCTOU re-stat).

    Returns {bin, pack_roots, libs: [...file_id...], ok_paths: [...]}.
    """
    rp = os.path.realpath(bin_path) if os.path.exists(bin_path) else bin_path
    roots = pack_search_dirs(rp) if os.path.isfile(rp) else []
    libs: List[dict] = []
    paths: List[str] = []
    if lib_paths is not None:
        for p in lib_paths:
            libs.append(_file_id(p))
            paths.append(p)
    elif os.path.isfile(rp):
        try:
            needed = read_needed(rp, needed_fn=needed_fn)
        except (OSError, ValueError):
            needed = []
        # Direct NEEDED pack sonames + walk one level of pack-local NEEDED targets.
        to_scan = [rp]
        seen_scan = {rp}
        pack_names = [n for n in needed if is_pack_soname(n)]
        for soname in needed:
            for hit in find_in_dirs(soname, roots):
                if hit not in seen_scan:
                    seen_scan.add(hit)
                    to_scan.append(hit)
        for soname in pack_names:
            for hit in find_in_dirs(soname, roots):
                if hit not in paths:
                    paths.append(hit)
                    libs.append(_file_id(hit))
        # Also fingerprint every libggml*/libllama* file sitting in pack roots
        # (covers dlopen backends not in DT_NEEDED of the main binary).
        for d in roots:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in names:
                if not is_pack_soname(name):
                    continue
                p = os.path.join(d, name)
                if not os.path.isfile(p):
                    continue
                rp_lib = os.path.realpath(p)
                if rp_lib not in paths:
                    paths.append(rp_lib)
                    libs.append(_file_id(rp_lib))
        # Walk NEEDED of already-found pack-local .so for more pack sonames.
        for target in list(to_scan)[1:]:
            try:
                for n2 in read_needed(target, needed_fn=needed_fn):
                    if not is_pack_soname(n2):
                        continue
                    for hit in find_in_dirs(n2, roots):
                        if hit not in paths:
                            paths.append(hit)
                            libs.append(_file_id(hit))
            except (OSError, ValueError):
                continue
    return {
        "bin": _file_id(rp),
        "pack_roots": roots,
        "libs": libs,
        "ok_paths": paths,
    }


def _same_file(a: str, b: str) -> bool:
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    return sa.st_ino == sb.st_ino and sa.st_dev == sb.st_dev


def refuse_soname_skew(
    bin_path: str,
    *,
    environ=None,
    needed_fn: Optional[Callable[[str], Sequence[str]]] = None,
) -> dict:
    """Check pack atomicity for a llama-server binary.

    Returns a JSON-serializable dict:
      ok: true/false
      reason: short code
      bin, pack_roots, resolved, mismatches, fingerprint
    """
    env = os.environ if environ is None else environ

    if sys.platform == "win32":
        return {
            "ok": True,
            "reason": "skipped_win",
            "bin": bin_path,
            "pack_roots": [],
            "resolved": {},
            "mismatches": [],
            "fingerprint": None,
            "hook": "refuse_soname_skew",
        }

    if not env_enabled(env):
        return {
            "ok": True,
            "reason": "disabled",
            "bin": bin_path,
            "pack_roots": [],
            "resolved": {},
            "mismatches": [],
            "fingerprint": None,
            "hook": "refuse_soname_skew",
        }

    if not bin_path:
        return {
            "ok": False,
            "reason": "missing_bin",
            "bin": bin_path,
            "pack_roots": [],
            "resolved": {},
            "mismatches": [{"error": "empty bin path"}],
            "fingerprint": None,
            "hook": "refuse_soname_skew",
        }

    if not os.path.isfile(bin_path):
        return {
            "ok": False,
            "reason": "bin_not_found",
            "bin": bin_path,
            "pack_roots": [],
            "resolved": {},
            "mismatches": [{"bin": bin_path, "error": "not a file"}],
            "fingerprint": None,
            "hook": "refuse_soname_skew",
        }

    rp = os.path.realpath(bin_path)
    roots = pack_search_dirs(rp)
    mismatches: List[dict] = []
    resolved: dict = {}

    not_elf_note = None
    try:
        needed = read_needed(rp, needed_fn=needed_fn)
    except ValueError as e:
        # Non-ELF (shell stub, script) — no DT_NEEDED, but still scan pack roots
        # for duplicate libggml*/libllama* across bin/ vs lib/ (galaxy2-class skew).
        needed = []
        not_elf_note = str(e)
    except OSError as e:
        return {
            "ok": False,
            "reason": "bin_unreadable",
            "bin": rp,
            "pack_roots": roots,
            "resolved": {},
            "mismatches": [{"bin": rp, "error": str(e)}],
            "fingerprint": None,
            "hook": "refuse_soname_skew",
        }

    # Collect pack sonames from the binary and one level of pack-local deps.
    pack_sonames: List[str] = []
    seen_names = set()
    scan_targets = [rp]
    scanned = {rp}

    def add_pack_name(n: str) -> None:
        if n not in seen_names and is_pack_soname(n):
            seen_names.add(n)
            pack_sonames.append(n)

    for n in needed:
        add_pack_name(n)
        # Pack-local non-filtered NEEDED still walks if file lives in pack
        # (already covered: libllama-server-impl matches libllama*).
        hits = find_in_dirs(n, roots)
        for h in hits:
            if h not in scanned:
                scanned.add(h)
                scan_targets.append(h)

    for target in scan_targets[1:]:
        try:
            for n2 in read_needed(target, needed_fn=needed_fn):
                add_pack_name(n2)
        except (OSError, ValueError):
            continue

    for soname in pack_sonames:
        hits = find_in_dirs(soname, roots)
        if not hits:
            mismatches.append(
                {
                    "soname": soname,
                    "error": "missing_in_pack",
                    "pack_roots": list(roots),
                    "bin": rp,
                }
            )
            continue
        # Multiple distinct files for same soname across bin/ vs lib/ → skew.
        unique: List[str] = []
        for h in hits:
            if not any(_same_file(h, u) for u in unique):
                unique.append(h)
        if len(unique) > 1:
            mismatches.append(
                {
                    "soname": soname,
                    "error": "bin_lib_pack_disagree",
                    "lib_packs": unique,
                    "pack_roots": list(roots),
                    "bin": rp,
                }
            )
            continue
        resolved[soname] = unique[0]

    # If pack roots include both dirname(bin) and a sibling lib/, and lib/ has
    # pack sonames that are *not* NEEDED and not present next to bin either,
    # that is fine. The galaxy2 case is mismatched *versions* of the same
    # soname — already handled by bin_lib_pack_disagree when both trees have it.
    # Extra: if lib/ exists and contains libggml*/libllama* that also exist next
    # to bin under the same basename but different identity — covered above via
    # find_in_dirs listing both.

    # Also scan pack roots for duplicate basenames with different identity even
    # when not in DT_NEEDED (dlopen backends like libggml-vulkan.so).
    by_base: dict = {}
    for d in roots:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not is_pack_soname(name):
                continue
            p = os.path.join(d, name)
            if not os.path.isfile(p):
                continue
            rp_lib = os.path.realpath(p)
            by_base.setdefault(name, [])
            if not any(_same_file(rp_lib, x) for x in by_base[name]):
                by_base[name].append(rp_lib)
    for name, paths in sorted(by_base.items()):
        if len(paths) > 1:
            # Avoid double-reporting if already in mismatches from NEEDED walk.
            if any(m.get("soname") == name and m.get("error") == "bin_lib_pack_disagree" for m in mismatches):
                continue
            mismatches.append(
                {
                    "soname": name,
                    "error": "bin_lib_pack_disagree",
                    "lib_packs": paths,
                    "pack_roots": list(roots),
                    "bin": rp,
                }
            )

    fp = fingerprint(rp, needed_fn=needed_fn, lib_paths=list(resolved.values()) or None)
    if mismatches:
        # Summarize which lib pack dirs participated.
        lib_pack_dirs = sorted({os.path.dirname(p) for m in mismatches for p in m.get("lib_packs", [])})
        return {
            "ok": False,
            "reason": "soname_skew",
            "bin": rp,
            "pack_roots": roots,
            "lib_packs_mismatched": lib_pack_dirs,
            "resolved": resolved,
            "mismatches": mismatches,
            "fingerprint": fp,
            "hook": "refuse_soname_skew",
            **({"note": not_elf_note} if not_elf_note else {}),
        }

    return {
        "ok": True,
        "reason": "not_elf" if not_elf_note else "ok",
        "bin": rp,
        "pack_roots": roots,
        "pack_root": roots[0] if roots else os.path.dirname(rp),
        "resolved": resolved,
        "mismatches": [],
        "fingerprint": fp,
        "hook": "refuse_soname_skew",
        **({"note": not_elf_note} if not_elf_note else {}),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse llama-server start on bin/lib soname skew")
    ap.add_argument("--bin", required=True, help="path to llama-server (or runtime) binary")
    ap.add_argument("--fingerprint-only", action="store_true", help="print fingerprint JSON only")
    a = ap.parse_args(argv)
    if a.fingerprint_only:
        print(json.dumps(fingerprint(a.bin), indent=2, sort_keys=True))
        return 0
    result = refuse_soname_skew(a.bin)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
