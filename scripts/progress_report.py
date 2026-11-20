#!/usr/bin/env python3
"""Build a refreshable hourly GitHub progress chart for Familia."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "brianreborn/familia"
WINDOW_DAYS = 14


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value):
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def iso_hour(value):
    return value.replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def gh_json(args):
    proc = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def collect(repo, now):
    since = (now - dt.timedelta(days=WINDOW_DAYS)).replace(minute=0, second=0, microsecond=0)
    since_arg = since.isoformat().replace("+00:00", "Z")
    issues = gh_json([
        f"repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=100&since={since_arg}",
        "--paginate", "--slurp",
    ])
    # gh --slurp returns one array per page. Flatten while keeping issues and PRs.
    items = [item for page in issues for item in page if parse_time(item.get("updated_at")) >= since]
    comments = gh_json([
        f"repos/{repo}/issues/comments?since={since_arg}&per_page=100", "--paginate", "--slurp",
    ])
    comments = [item for page in comments for item in page]
    review_comments = gh_json([
        f"repos/{repo}/pulls/comments?since={since_arg}&per_page=100", "--paginate", "--slurp",
    ])
    review_comments = [item for page in review_comments for item in page]
    pulls = gh_json([
        f"repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100", "--paginate", "--slurp",
    ])
    pulls = [item for page in pulls for item in page]
    pull_by_number = {item["number"]: item for item in pulls}
    item_by_number = {item["number"]: item for item in items}

    events = []
    for item in items:
        number = item["number"]
        is_pr = "pull_request" in item
        kind = "pull request" if is_pr else "issue"
        created = parse_time(item.get("created_at"))
        closed = parse_time(item.get("closed_at"))
        pull = pull_by_number.get(number, {}) if is_pr else {}
        merged = parse_time(pull.get("merged_at"))
        if created and created >= since:
            events.append({"at": created, "type": "opened", "number": number, "title": item["title"], "kind": kind})
        if merged and merged >= since:
            events.append({"at": merged, "type": "merged", "number": number, "title": item["title"], "kind": kind})
        elif item.get("state") == "closed" and closed and closed >= since:
            events.append({"at": closed, "type": "closed", "number": number, "title": item["title"], "kind": kind})

    for comment in comments:
        at = parse_time(comment.get("created_at"))
        if not at or at < since:
            continue
        issue_url = comment.get("issue_url", "")
        number = int(issue_url.rstrip("/").split("/")[-1])
        parent = item_by_number.get(number)
        if parent:
            events.append({
                "at": at, "type": "comment", "number": number,
                "title": parent["title"], "kind": "pull request" if "pull_request" in parent else "issue",
                "actor": (comment.get("user") or {}).get("login", "unknown"),
            })

    for comment in review_comments:
        at = parse_time(comment.get("created_at"))
        if not at or at < since:
            continue
        number = int(comment.get("pull_request_url", "").rstrip("/").split("/")[-1])
        parent = item_by_number.get(number)
        if parent:
            events.append({
                "at": at, "type": "review", "number": number,
                "title": parent["title"], "kind": "pull request",
                "actor": (comment.get("user") or {}).get("login", "unknown"),
            })

    active = []
    for item in items:
        if item.get("state") != "open":
            continue
        updated = parse_time(item.get("updated_at"))
        if updated and updated >= since:
            active.append({
                "number": item["number"], "title": item["title"],
                "kind": "pull request" if "pull_request" in item else "issue",
                "created_at": item.get("created_at"), "updated_at": item.get("updated_at"),
                "labels": [label["name"] for label in item.get("labels", [])],
                "url": item.get("html_url", ""),
            })
    events.sort(key=lambda event: event["at"])
    return {
        "repo": repo, "generated_at": now.isoformat().replace("+00:00", "Z"),
        "since": since.isoformat().replace("+00:00", "Z"),
        "until": now.isoformat().replace("+00:00", "Z"),
        "items": active, "events": [{**event, "at": event["at"].isoformat().replace("+00:00", "Z")} for event in events],
    }


def series(data):
    start = parse_time(data["since"])
    end = parse_time(data["until"])
    buckets = []
    cursor = start
    while cursor <= end:
        buckets.append(iso_hour(cursor))
        cursor += dt.timedelta(hours=1)
    counts = {key: Counter() for key in ("comment", "review", "opened", "closed", "merged")}
    for event in data["events"]:
        key = event["type"]
        if key in counts:
            counts[key][iso_hour(parse_time(event["at"]))] += 1
    return buckets, counts


def svg_chart(data):
    buckets, counts = series(data)
    width, height = 1120, 360
    left, right, top, bottom = 54, 18, 30, 52
    plot_w, plot_h = width - left - right, height - top - bottom
    max_value = max(1, max((sum(counts[k][hour] for k in counts) for hour in buckets), default=0))
    slot = plot_w / max(1, len(buckets))
    bar_w = max(1.2, slot * 0.78)
    colors = {"comment": "#2c6e73", "review": "#397f9a", "opened": "#d39b37", "closed": "#557a61", "merged": "#ce6848"}
    parts = [f'<svg class="activity" viewBox="0 0 {width} {height}" role="img" aria-label="Hourly GitHub issue and pull request activity">']
    for tick in range(5):
        y = top + plot_h * tick / 4
        label = round(max_value * (4 - tick) / 4)
        parts.append(f'<line x1="{left}" x2="{width-right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/><text x="{left-12}" y="{y+4:.1f}" text-anchor="end" class="axis">{label}</text>')
    for index, hour in enumerate(buckets):
        x = left + index * slot + (slot - bar_w) / 2
        stack = 0
        for key in ("comment", "review", "opened", "closed", "merged"):
            value = counts[key][hour]
            if not value:
                continue
            bar_h = value / max_value * plot_h
            y = top + plot_h - stack - bar_h
            parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" fill="{colors[key]}"/>')
            stack += bar_h
    for day in range(15):
        x = left + plot_w * day / 14
        label = (parse_time(data["since"]) + dt.timedelta(days=day)).strftime("%b %d")
        parts.append(f'<text x="{x:.1f}" y="{height-18}" text-anchor="middle" class="axis">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def gantt(data):
    start, end = parse_time(data["since"]), parse_time(data["until"])
    span = max(1, (end - start).total_seconds())
    items = sorted(data["items"], key=lambda item: item["updated_at"], reverse=True)
    rows = []
    for item in items[:90]:
        created = max(start, parse_time(item["created_at"]))
        updated = min(end, parse_time(item["updated_at"]))
        x = max(0, (created - start).total_seconds() / span * 100)
        w = max(0.7, (updated - created).total_seconds() / span * 100)
        title = html.escape(item["title"])
        href = html.escape(item["url"], quote=True)
        label = f'#{item["number"]} {title}'
        kind = "pr" if item["kind"] == "pull request" else "issue"
        rows.append(f'<div class="lane"><a class="lane-label" href="{href}" title="{label}">{label}</a><div class="track"><a class="bar {kind}" style="left:{x:.3f}%;width:{w:.3f}%" href="{href}" title="Opened {created:%Y-%m-%d}; last activity {updated:%Y-%m-%d}"></a></div><span class="lane-state">{kind} · {updated:%b %d}</span></div>')
    return "".join(rows) if rows else '<p class="empty">No recently active open issues or pull requests in this window.</p>'


def render(data):
    counts = Counter(event["type"] for event in data["events"])
    active_issues = sum(item["kind"] == "issue" for item in data["items"])
    active_prs = len(data["items"]) - active_issues
    stamp = parse_time(data["generated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    since_label = parse_time(data["since"]).strftime("%b %d")
    until_label = parse_time(data["until"]).strftime("%b %d")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Familia progress · 14 days</title>
<style>
:root{{--paper:#f4f3ed;--ink:#172a2c;--muted:#667476;--line:#c9d1c9;--teal:#2c6e73;--gold:#d39b37;--green:#557a61;--coral:#ce6848;--white:#fffef9}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 "Avenir Next",Avenir,"Segoe UI",sans-serif}}main{{max-width:1320px;margin:auto;padding:28px 34px 60px}}header{{display:flex;align-items:end;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:18px}}h1{{font:600 36px/1.05 Georgia,"Iowan Old Style",serif;margin:0}}.eyebrow{{font-size:11px;text-transform:uppercase;letter-spacing:1.6px;color:var(--teal);font-weight:700;margin-bottom:8px}}.stamp{{color:var(--muted);font-size:13px}}.stats{{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));border-bottom:1px solid var(--line);margin:18px 0 24px}}.stat{{padding:13px 10px 16px 0;border-right:1px solid var(--line)}}.stat:not(:first-child){{padding-left:18px}}.num{{font:600 29px/1 Georgia,serif}}.cap{{color:var(--muted);font-size:12px;margin-top:7px}}section{{margin-top:24px}}h2{{font:600 21px/1.2 Georgia,serif;margin:0 0 6px}}.sub{{color:var(--muted);font-size:13px;margin:0 0 12px}}.chart-wrap{{background:var(--white);border:1px solid var(--line);padding:10px 12px 0}}svg{{display:block;width:100%;height:auto}}.grid{{stroke:#dce1db;stroke-width:1}}.axis{{fill:var(--muted);font:11px sans-serif}}.legend{{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--muted);padding:5px 0 12px}}.swatch{{display:inline-block;width:9px;height:9px;margin-right:6px;border-radius:2px}}.gantt-head{{display:grid;grid-template-columns:minmax(210px,30%) 1fr 100px;color:var(--muted);font-size:11px;border-bottom:1px solid var(--line);padding:6px 0}}.lane{{display:grid;grid-template-columns:minmax(210px,30%) 1fr 100px;gap:12px;align-items:center;min-height:26px;border-bottom:1px solid #dfe3dd}}.lane-label{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink);text-decoration:none;font-size:12px}}.lane-label:hover{{color:var(--teal);text-decoration:underline}}.track{{height:10px;position:relative;background:repeating-linear-gradient(90deg,transparent 0,transparent calc(7.14% - 1px),#dfe3dd calc(7.14% - 1px),#dfe3dd 7.14%)}}.bar{{position:absolute;height:8px;top:1px;border-radius:4px;background:var(--teal)}}.bar.pr{{background:var(--coral)}}.lane-state{{color:var(--muted);font-size:11px;white-space:nowrap}}.empty{{color:var(--muted)}}footer{{margin-top:28px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:12px}}@media(max-width:720px){{main{{padding:20px 14px}}h1{{font-size:29px}}header{{display:block}}.stamp{{margin-top:10px}}.stats{{grid-template-columns:repeat(2,1fr);row-gap:8px}}.stat:not(:first-child){{padding-left:0}}.gantt-head,.lane{{grid-template-columns:minmax(120px,40%) 1fr 62px;gap:6px}}.lane-label{{font-size:11px}}.lane-state{{font-size:10px}}}}
</style></head><body><main>
<header><div><div class="eyebrow">Familia · issue and PR activity</div><h1>Progress, hour by hour</h1></div><div class="stamp">Last 14 days · refreshed {stamp}</div></header>
<div class="stats"><div class="stat"><div class="num">{counts['comment']}</div><div class="cap">Issue-thread comments</div></div><div class="stat"><div class="num">{counts['review']}</div><div class="cap">PR review comments</div></div><div class="stat"><div class="num">{counts['opened']}</div><div class="cap">Opened</div></div><div class="stat"><div class="num">{counts['closed']}</div><div class="cap">Closed</div></div><div class="stat"><div class="num">{counts['merged']}</div><div class="cap">Merged PRs</div></div><div class="stat"><div class="num">{active_issues + active_prs}</div><div class="cap">Recently active · {active_issues} issues / {active_prs} PRs</div></div></div>
<section><h2>Hourly activity</h2><p class="sub">Each bar is one UTC hour. Issue-thread comments, PR review comments, and lifecycle events are separate stacked series.</p><div class="chart-wrap">{svg_chart(data)}<div class="legend"><span><i class="swatch" style="background:#2c6e73"></i>Issue-thread comments</span><span><i class="swatch" style="background:#397f9a"></i>PR review comments</span><span><i class="swatch" style="background:#d39b37"></i>Opened</span><span><i class="swatch" style="background:#557a61"></i>Closed</span><span><i class="swatch" style="background:#ce6848"></i>Merged</span></div></div></section>
<section><h2>Currently active · Gantt view</h2><p class="sub">Open items updated in this window, newest activity first (showing at most 90). Bars span creation to latest update, clipped to the chart window; these are issue timelines, not assigned-work estimates.</p><div class="gantt-head"><span>Issue / pull request</span><span>{since_label} <span style="float:right">{until_label}</span></span><span>Last update</span></div>{gantt(data)}</section>
<footer>Source: GitHub REST API for {html.escape(data['repo'])}. All times UTC. Activity means a timestamped issue-thread comment, PR review comment, or lifecycle event; it does not prove implementation progress. Report data: <code>progress-data.json</code>.</footer>
</main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO))
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "progress")
    parser.add_argument("--now", help="fixed UTC timestamp for reproducible tests")
    args = parser.parse_args()
    now = parse_time(args.now) if args.now else utc_now()
    data = collect(args.repo, now)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "progress-data.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "index.html").write_text(render(data), encoding="utf-8")
    print(f"wrote {args.out_dir / 'index.html'} ({len(data['events'])} events, {len(data['items'])} open active items)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"progress-report: GitHub data collection failed: {exc}", file=sys.stderr)
        raise SystemExit(1)