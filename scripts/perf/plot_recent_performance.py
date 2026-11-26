#!/usr/bin/env python3
"""Plot measured performance anchors already recorded in the Familia ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in data["rows"] if row.get("valid")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=Path("docs/perf/valid-2026-10-27/fleet-perf-summary.json"))
    ap.add_argument("--output", type=Path, default=Path("docs/perf/charts/recent-measured-performance.png"))
    args = ap.parse_args()
    rows = load(args.summary)
    miryam = sorted((r for r in rows if r["host"] == "miryam" and r["model"] == "SmolLM2-135M-Instruct"),
                    key=lambda r: (r["threads"], r["test"]))
    phone = [r for r in rows if r["host"] == "phone8" and r["model"] == "SmolLM2-135M-Instruct"]
    pp = [(r["threads"], r["tok_s"]) for r in miryam if r["test"] == "pp256"]
    tg = [(r["threads"], r["tok_s"]) for r in miryam if r["test"] == "tg64"]
    phone_pp = next((r["tok_s"] for r in phone if r["test"] == "pp128"), None)
    phone_tg = next((r["tok_s"] for r in phone if r["test"] == "tg64"), None)
    labels, values, colors = [], [], []
    if phone_pp is not None:
        labels.append("phone8\nVulkan pp128"); values.append(phone_pp); colors.append("#4c78a8")
    if phone_tg is not None:
        labels.append("phone8\nVulkan tg64"); values.append(phone_tg); colors.append("#4c78a8")
    labels += ["miryam\nCPU pp256\n3 threads", "miryam\nCPU tg64\n2 threads"]
    values += [next(y for x, y in pp if x == 3), next(y for x, y in tg if x == 2)]
    colors += ["#f58518", "#f58518"]
    # Dependency-free SVG keeps chart generation available on minimal fleet hosts.
    width, height, left, top, bottom = 1200, 520, 70, 70, 430
    max_y = max(values + [y for _, y in pp + tg]) * 1.18
    def y(v): return bottom - (v / max_y) * (bottom - top)
    def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<style>text{font:14px sans-serif;fill:#202124}.grid{stroke:#d9d9d9}.axis{stroke:#444}.line{fill:none;stroke:#2563eb;stroke-width:3}.line2{fill:none;stroke:#d97706;stroke-width:3}.dot{fill:#2563eb}.dot2{fill:#d97706}.bar1{fill:#4c78a8}.bar2{fill:#f58518}</style>',
           '<rect width="100%" height="100%" fill="white"/>', '<text x="600" y="30" text-anchor="middle" font-size="18">Familia measured performance (no engine-change claim)</text>',
           '<text x="300" y="58" text-anchor="middle">Miryam: SmolLM2 CPU thread sweep</text>', '<text x="900" y="58" text-anchor="middle">Recorded anchors, different conditions</text>']
    for i in range(6):
        gy = top + i * (bottom - top) / 5
        val = max_y * (5 - i) / 5
        out += [f'<line class="grid" x1="50" y1="{gy:.1f}" x2="560" y2="{gy:.1f}"/>', f'<text x="44" y="{gy+5:.1f}" text-anchor="end">{val:.0f}</text>',
                f'<line class="grid" x1="640" y1="{gy:.1f}" x2="1160" y2="{gy:.1f}"/>']
    out += ['<line class="axis" x1="50" y1="430" x2="560" y2="430"/>', '<line class="axis" x1="50" y1="70" x2="50" y2="430"/>', '<text x="305" y="505" text-anchor="middle">threads / anchor</text>', '<text x="15" y="250" transform="rotate(-90 15 250)" text-anchor="middle">tokens/s</text>']
    xs = [130 + i * 150 for i in range(len(pp))]
    for (x, v), (_, tv) in zip(zip(xs, [v for _, v in pp]), tg):
        out += [f'<circle class="dot" cx="{x}" cy="{y(v):.1f}" r="5"/>', f'<text x="{x}" y="450" text-anchor="middle">{x and pp[xs.index(x)][0]}</text>']
    out += ['<polyline class="line" points="' + ' '.join(f'{x},{y(v):.1f}' for x, (_, v) in zip(xs, pp)) + '"/>', '<polyline class="line2" points="' + ' '.join(f'{x},{y(v):.1f}' for x, (_, v) in zip(xs, tg)) + '"/>']
    out += ['<text x="400" y="90" fill="#2563eb">prompt 256</text>', '<text x="400" y="110" fill="#d97706">decode 64</text>']
    bar_w = 90
    for i, (label, value, color) in enumerate(zip(labels, values, colors)):
        x = 680 + i * 120
        out.append(f'<rect class="{"bar1" if color == "#4c78a8" else "bar2"}" x="{x}" y="{y(value):.1f}" width="{bar_w}" height="{430-y(value):.1f}"/>')
        out.append(f'<text x="{x+bar_w/2}" y="{y(value)-8:.1f}" text-anchor="middle">{value:.1f}</text>')
        for j, line in enumerate(label.split("\\n")):
            out.append(f'<text x="{x+bar_w/2}" y="{450+j*16}" text-anchor="middle">{esc(line)}</text>')
    out.append('</svg>')
    args.output = args.output.with_suffix('.svg')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
