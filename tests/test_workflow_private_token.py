"""H1: the familia-private log token must only reach a job that never runs tested code."""
import pathlib
import yaml

WF = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _jobs():
    for f in sorted(WF.glob("*.yml")):
        doc = yaml.safe_load(f.read_text())
        for name, job in (doc.get("jobs") or {}).items():
            yield f.name, name, job


def test_private_token_job_runs_no_checked_out_code():
    seen = False
    for fname, name, job in _jobs():
        if "FAMILIA_PRIVATE_LOGS_TOKEN" not in yaml.safe_dump(job):
            continue
        seen = True
        where = f"{fname}:{name}"
        assert job.get("runs-on") == "ubuntu-latest", f"{where} must run on a GitHub-hosted runner"
        for step in job.get("steps", []):
            uses = step.get("uses", "")
            assert not uses.startswith("actions/checkout"), f"{where} must not check out code"
            run = step.get("run", "")
            assert "sh scripts/" not in run and "tests/" not in run, f"{where} must not run repo scripts"
    assert seen, "expected the upload job to reference the token"
