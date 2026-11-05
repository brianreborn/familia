#!/usr/bin/env python3
"""Pick a default phone model id from device RAM (policy defaults; adjustable).

Policy uses *usable* MiB = total_ram_mib - reserve_ram_mib (default reserve 5120,
matching install/termux/install.sh). Override with FAMILIA_PHONE_MODEL (exact
graph model id) or FAMILIA_PHONE_MODEL_TIER (tiny|small|medium|large).

Tiers (defaults — not a hard cap; operators may override):

  usable MiB     tier     default graph model id
  ------------   ------   ---------------------------------
  < 1024         tiny     smollm2-135m-q4-phone
  < 2048         small    qwen25-05b-q4km-phone
  < 4096         medium   lfm3-17b-uncensored-q4km
  >= 4096        large    dolphin3-cyber-8b-q2k

On a ~7.4 GiB Galaxy A57 with reserve 5120, usable is ~2.4 GiB -> medium (LFM3).
Dolphin3 Q2_K (~3 GiB) needs the large tier (more RAM or a lower reserve).

Usage:
  python3 install/termux/phone-model-default.py [--ram-mib N] [--reserve-mib N]
                                                [--json] [--list-tiers]
"""
from __future__ import annotations

import json
import os
import sys

TIERS = (
    # (max_usable_exclusive, tier_name, model_id, note)
    (1024, "tiny", "smollm2-135m-q4-phone", "decision-sized; fits very tight phones"),
    (2048, "small", "qwen25-05b-q4km-phone", "general ~0.5B Q4"),
    (4096, "medium", "lfm3-17b-uncensored-q4km", "familia default chat ~1-2 GiB Q4"),
    (None, "large", "dolphin3-cyber-8b-q2k", "guardian Dolphin3-Cyber Q2_K ~3 GiB; needs Llama 3.1 license"),
)

DEFAULT_RESERVE = int(os.environ.get("FAMILIA_RESERVE_MIB", "5120"))


def read_total_ram_mib() -> int | None:
    path = "/proc/meminfo"
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except OSError:
        return None
    return None


def pick(usable: int) -> tuple[str, str, str]:
    for vmax, tier, model, note in TIERS:
        if vmax is None or usable < vmax:
            return tier, model, note
    # unreachable; last tier catches all
    return TIERS[-1][1], TIERS[-1][2], TIERS[-1][3]


def main(argv: list[str]) -> int:
    ram = None
    reserve = DEFAULT_RESERVE
    as_json = False
    list_tiers = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        if a == "--json":
            as_json = True
        elif a == "--list-tiers":
            list_tiers = True
        elif a == "--ram-mib" and i + 1 < len(argv):
            ram = int(argv[i + 1]); i += 1
        elif a == "--reserve-mib" and i + 1 < len(argv):
            reserve = int(argv[i + 1]); i += 1
        else:
            print(f"phone-model-default: unknown option {a!r}", file=sys.stderr)
            return 2
        i += 1

    if list_tiers:
        rows = [
            {
                "tier": t,
                "usable_mib_lt": vmax,
                "model": m,
                "note": n,
            }
            for vmax, t, m, n in TIERS
        ]
        if as_json:
            print(json.dumps({"reserve_default_mib": DEFAULT_RESERVE, "tiers": rows}, indent=2))
        else:
            print(f"reserve_default_mib={DEFAULT_RESERVE} (adjustable via FAMILIA_RESERVE_MIB)")
            print("usable_mib = total_ram_mib - reserve_mib")
            for row in rows:
                bound = f"< {row['usable_mib_lt']}" if row["usable_mib_lt"] is not None else ">= previous"
                print(f"  {row['tier']:7} usable {bound:12} -> {row['model']}  # {row['note']}")
            print("override: FAMILIA_PHONE_MODEL=<graph model id> or FAMILIA_PHONE_MODEL_TIER=tiny|small|medium|large")
        return 0

    override = os.environ.get("FAMILIA_PHONE_MODEL", "").strip()
    tier_override = os.environ.get("FAMILIA_PHONE_MODEL_TIER", "").strip().lower()

    if ram is None:
        ram = read_total_ram_mib()
    if ram is None and not override and not tier_override:
        print("phone-model-default: could not read MemTotal; pass --ram-mib or set FAMILIA_PHONE_MODEL",
              file=sys.stderr)
        return 2

    usable = (ram - reserve) if ram is not None else None
    # Phones under ~6 GiB with reserve 5120 can yield negative usable; clamp to 0.
    if usable is not None and usable < 0:
        usable = 0
    if override:
        tier, model, note = "override", override, "FAMILIA_PHONE_MODEL"
    elif tier_override:
        match = [t for t in TIERS if t[1] == tier_override]
        if not match:
            print(f"phone-model-default: unknown tier {tier_override!r}", file=sys.stderr)
            return 2
        _, tier, model, note = match[0]
    else:
        assert usable is not None
        tier, model, note = pick(usable)

    payload = {
        "total_ram_mib": ram,
        "reserve_mib": reserve,
        "usable_mib": usable,
        "tier": tier,
        "model": model,
        "note": note,
        "adjustable": True,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(model)
        print(
            f"phone-model-default: tier={tier} model={model} "
            f"total_ram_mib={ram} reserve_mib={reserve} usable_mib={usable} ({note})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
