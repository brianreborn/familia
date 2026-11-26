"""Shared loopback check (TR-6, docs/config/routing-spec.md CFG-SPEC-TOOLS-004).

Stdlib only and imports nothing from scripts/, so any module can use it without
an import cycle. Never resolves DNS: `ipaddress` parses literals only.
"""
import ipaddress

__all__ = ["is_loopback"]


def is_loopback(host):
    """True only for a literal loopback host or bind. Never resolves DNS.

    Accepts:
      - 'localhost' (any ASCII case, surrounding whitespace stripped; exact label only)
      - IPv4 127.0.0.0/8
      - IPv6 ::1 (any legal textual form), optional [brackets]
      - IPv4-mapped IPv6 ::ffff:127.0.0.0/8, optional [brackets]
      - IPv6 zone-id forms of the above, after stripping a trailing %zone
        (the zone name is never looked up)

    Rejects (fail-closed):
      - None, '', whitespace-only, or anything ipaddress cannot parse
      - 0.0.0.0, ::, [::], ::ffff:0.0.0.0 (unspecified / wildcard)
      - any other DNS name, including 'localhost.', 'localhost.evil',
        '127.example', '127.0.0.1.evil' (the old startswith("127.") bypass)
      - host:port, leading-zero IPv4, short, integer or hex forms
      - link-local, private and public addresses

    Callers pass a hostname or bind address, never host:port.
    """
    b = str(host or "").strip()
    if b.lower() == "localhost":
        return True
    if b.startswith("[") and b.endswith("]"):
        b = b[1:-1]
    if "%" in b:
        b, zone = b.split("%", 1)
        if not zone or ":" not in b:
            return False  # only IPv6 literals carry a zone id
    try:
        ip = ipaddress.ip_address(b)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback
