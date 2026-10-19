#!/usr/bin/env python3
"""familia_yaml.py: read graph.yaml with PyYAML when present, else a small stdlib reader.

The stdlib reader covers the subset graph.yaml uses (block mappings, '- ' lists,
flow lists/maps, quoted and plain scalars, comments, '>'/'|' block scalars), so
licenses.py and skills.py work on a fresh phone or an old box without PyYAML.
It is a reader only. Edits go through set_node_list(), which rewrites one line
in place and keeps every comment in graph.yaml.
"""
import re

try:  # pragma: no cover - depends on the host
    import yaml as _yaml
except Exception:  # noqa: BLE001
    _yaml = None


def _strip_comment(s):
    out, q = [], None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _split_flow(s):
    parts, depth, q, cur = [], 0, None, []
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip()); cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _scalar(v):
    v = v.strip()
    if v == "" or v in ("~", "null", "Null", "NULL"):
        return None
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in _split_flow(v[1:-1])]
    if v.startswith("{") and v.endswith("}"):
        d = {}
        for x in _split_flow(v[1:-1]):
            k, _, val = x.partition(":")
            d[_scalar(k)] = _scalar(val)
        return d
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v in ("true", "True", "yes"):
        return True
    if v in ("false", "False", "no"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d*", v):
        return float(v)
    return v


def _lines(text):
    out, skip_indent = [], None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        ind = len(raw) - len(raw.lstrip(" "))
        if skip_indent is not None:
            if ind > skip_indent:
                continue
            skip_indent = None
        s = _strip_comment(raw)
        if not s.strip():
            continue
        if re.search(r":\s*[>|][-+]?$", s):
            skip_indent = ind
            s = re.sub(r"[>|][-+]?$", "''", s)
        out.append((ind, s.strip()))
    return out


def _parse(lines, i, ind):
    if i < len(lines) and lines[i][1].startswith("- "):
        res = []
        while i < len(lines) and lines[i][0] == ind and lines[i][1].startswith("- "):
            body = lines[i][1][2:]
            if re.match(r"^[^\[{'\"][^:]*:(\s|$)", body):
                lines[i] = (ind + 2, body)
                val, i = _parse(lines, i, ind + 2)
                res.append(val)
            else:
                res.append(_scalar(body)); i += 1
        return res, i
    res = {}
    while i < len(lines) and lines[i][0] == ind:
        s = lines[i][1]
        k, sep, v = s.partition(":")
        if not sep:
            i += 1; continue
        key = _scalar(k)
        i += 1
        if v.strip():
            res[key] = _scalar(v)
        elif i < len(lines) and lines[i][0] > ind:
            res[key], i = _parse(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == ind and lines[i][1].startswith("- "):
            res[key], i = _parse(lines, i, ind)
        else:
            res[key] = None
    return res, i


def loads(text, force_stdlib=False):
    if _yaml is not None and not force_stdlib:
        return _yaml.safe_load(text) or {}
    lines = _lines(text)
    if not lines:
        return {}
    val, _ = _parse(lines, 0, lines[0][0])
    return val


def load(path, force_stdlib=False):
    with open(path, encoding="utf-8") as fh:
        return loads(fh.read(), force_stdlib)


def set_node_list(text, section, name, key, values):
    """Set section.name.key to an inline list, editing only that line (or adding it).

    Returns the new text. Raises KeyError when section.name is not in the file.
    """
    lines = text.split("\n")
    sec_i = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", l)), None)
    if sec_i is None:
        raise KeyError(f"{section} section not found")
    node_i = node_ind = None
    for i in range(sec_i + 1, len(lines)):
        l = lines[i]
        if l and not l[0].isspace() and not l.startswith("#"):
            break
        m = re.match(rf"^(\s+){re.escape(name)}:\s*(#.*)?$", l)
        if m:
            node_i, node_ind = i, len(m.group(1)); break
    if node_i is None:
        raise KeyError(f"{section}.{name} not found")
    end, child_ind = node_i + 1, None
    while end < len(lines):
        l = lines[end]
        if l.strip() and not l.lstrip().startswith("#"):
            ind = len(l) - len(l.lstrip(" "))
            if ind <= node_ind:
                break
            child_ind = child_ind or ind
        end += 1
    child_ind = child_ind or node_ind + 2
    rendered = " " * child_ind + f"{key}: [" + ", ".join(values) + "]"
    for i in range(node_i + 1, end):
        if re.match(rf"^\s{{{child_ind}}}{re.escape(key)}:", lines[i]):
            m = re.search(r"\]\s*(#.*)$", lines[i])
            comment = "  " + m.group(1) if m else ""
            lines[i] = rendered + comment
            return "\n".join(lines)
    last = end
    while last > node_i + 1 and not lines[last - 1].strip():
        last -= 1
    lines.insert(last, rendered)
    return "\n".join(lines)
