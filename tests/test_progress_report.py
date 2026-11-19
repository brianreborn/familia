import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("progress_report", ROOT / "scripts" / "progress_report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def sample_data():
    return {
        "repo": "brianreborn/familia",
        "generated_at": "2026-11-19T12:30:00Z",
        "since": "2026-11-05T12:00:00Z",
        "until": "2026-11-19T12:30:00Z",
        "events": [
            {"at": "2026-11-19T10:12:00Z", "type": "comment", "number": 664, "title": "Network issue", "kind": "issue"},
            {"at": "2026-11-19T10:37:00Z", "type": "review", "number": 663, "title": "Runtime pins", "kind": "pull request"},
            {"at": "2026-11-19T10:45:00Z", "type": "merged", "number": 663, "title": "Runtime pins", "kind": "pull request"},
            {"at": "2026-11-19T11:10:00Z", "type": "opened", "number": 665, "title": "New bug", "kind": "issue"},
        ],
        "items": [
            {"number": 664, "title": "Network issue", "kind": "issue", "created_at": "2026-11-18T10:00:00Z", "updated_at": "2026-11-19T10:12:00Z", "labels": ["bug"], "url": "https://github.com/brianreborn/familia/issues/664"},
            {"number": 665, "title": "New bug", "kind": "issue", "created_at": "2026-11-19T11:10:00Z", "updated_at": "2026-11-19T11:10:00Z", "labels": [], "url": "https://github.com/brianreborn/familia/issues/665"},
        ],
    }


def test_series_buckets_utc_events_by_hour():
    buckets, counts = REPORT.series(sample_data())
    assert buckets[0] == "2026-11-05T12:00:00Z"
    assert counts["comment"]["2026-11-19T10:00:00Z"] == 1
    assert counts["review"]["2026-11-19T10:00:00Z"] == 1
    assert counts["merged"]["2026-11-19T10:00:00Z"] == 1


def test_render_contains_hourly_chart_and_open_work_gantt():
    page = REPORT.render(sample_data())
    assert "Progress, hour by hour" in page
    assert "Hourly activity" in page
    assert "Currently active" in page
    assert "#664 Network issue" in page
    assert page.index("#665 New bug") < page.index("#664 Network issue")
    assert "Merged PRs" in page
    assert "PR review comments" in page
    assert "Nov 05" in page and "Nov 19" in page
    assert "not assigned-work estimates" in page