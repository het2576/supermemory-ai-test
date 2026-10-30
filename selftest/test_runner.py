import json

import pytest

from src.clock import FakeClock
from src.cycle import run_cycle
from src.providers.mock import Bugs, MockConfig, MockProvider
from src.recorder import scrub
from src.runner import RunOutcome, TestDef, aggregate, run_test


@pytest.mark.parametrize("cat, runs, want", [
    ("DEL", ["PASS", "PASS", "PASS"], "PASS"),
    ("DEL", ["PASS", "FAIL", "PASS"], "FAIL"),      # any run still present at 600s => FAIL (S1 candidate)
    ("DEL", ["PASS", "SLOW", "PASS"], "SLOW"),
    ("DEL", ["SLOW", "FAIL", "PASS"], "FAIL"),
    ("ISO", ["PASS", "FAIL", "PASS"], "FAIL"),      # intermittent leak is still a FAIL candidate
    ("COR", ["PASS", "FAIL", "PASS"], "INCONCLUSIVE"),
    ("LAT", ["SKIPPED"] * 3, "SKIPPED"),
    ("DEL", ["PASS", "ERROR", "PASS"], "ERROR"),    # harness errors are never findings
])
def test_aggregate_rules(cat, runs, want):
    assert aggregate(cat, runs) == want


CYCLE = TestDef("CYCLE-00", "DEL", "harness add/search/delete cycle", lambda ctx: run_cycle(ctx.provider, ctx.clock))


def run(tmp_path, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(bugs=Bugs(**bugs)), clock)
    return run_test(CYCLE, p, runs=3, clock=clock, results_base=tmp_path, log=lambda s: None), tmp_path


def test_three_runs_all_pass(tmp_path):
    res, base = run(tmp_path)
    assert res.final == "PASS" and res.per_run == ["PASS"] * 3
    day = next((base / "runs").iterdir())
    assert sorted(f.name for f in day.iterdir()) == ["CYCLE-00-run1.json", "CYCLE-00-run2.json", "CYCLE-00-run3.json", "results.json"]


def test_delete_noop_is_fail_in_every_run(tmp_path):
    res, _ = run(tmp_path, delete_noop=True)
    assert res.final == "FAIL" and res.per_run == ["FAIL"] * 3


def test_intermittent_delete_bug_is_still_fail(tmp_path):
    # 2nd delete of three is a silent no-op => PASS, FAIL, PASS => aggregated FAIL (reported as n/3)
    res, _ = run(tmp_path, flaky_delete_every=2)
    assert res.per_run == ["PASS", "FAIL", "PASS"]
    assert res.final == "FAIL"


def test_results_json_has_the_prd_schema_fields(tmp_path):
    _, base = run(tmp_path)
    data = json.loads((next((base / "runs").iterdir()) / "results.json").read_text())
    rec = data["records"][0]
    for k in ("testId", "provider", "client", "apiVersion", "date", "run", "checkpoints", "result", "timeToConsistencySec", "notes", "rawArtifacts"):
        assert k in rec
    assert data["summary"][0]["final"] == "PASS"


def test_harness_exception_becomes_error_not_fail(tmp_path):
    def boom(ctx):
        raise RuntimeError("network down")

    t = TestDef("BOOM-00", "DEL", "raises", boom)
    clock = FakeClock()
    res = run_test(t, MockProvider(clock=clock), runs=3, clock=clock, results_base=tmp_path, log=lambda s: None)
    assert res.final == "ERROR"


def test_api_key_is_stripped_from_evidence_files(tmp_path):
    secret = "sm_SECRET_KEY_12345678"

    def leaky(ctx):
        return RunOutcome("PASS", notes=f"oops {secret}", extra={"echo": secret})

    t = TestDef("LEAK-00", "DEL", "leaks key", leaky)
    clock = FakeClock()
    run_test(t, MockProvider(clock=clock), runs=1, api_key=secret, clock=clock, results_base=tmp_path, log=lambda s: None)
    day = next((tmp_path / "runs").iterdir())
    blob = (day / "LEAK-00-run1.json").read_text()
    assert secret not in blob and "[REDACTED]" in blob


def test_scrub_ignores_short_or_empty_secrets():
    assert scrub({"a": "abc"}, ["", "abc"]) == {"a": "abc"}
