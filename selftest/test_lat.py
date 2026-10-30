"""Do the LAT tests measure what they claim? The mock has known delays, so the recovered numbers must match them."""

import importlib.util
import json
from pathlib import Path

from src.clock import FakeClock
from src.latency import fmt, percentile, summarize
from src.providers.mock import MockConfig, MockProvider
from src.runner import run_test

_spec = importlib.util.spec_from_file_location("product_test_lat", Path(__file__).parent.parent / "tests" / "test_lat.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TESTS = {t.id: t for t in _mod.TESTS}


def go(test_id, tmp_path, **config):
    clock = FakeClock()
    p = MockProvider(MockConfig(**config), clock)
    return run_test(TESTS[test_id], p, runs=1, clock=clock, results_base=tmp_path, log=lambda s: None)


def extra(result):
    return json.loads(Path(result.records[0]["rawArtifacts"]).read_text())["extra"]


# --- statistics ------------------------------------------------------------------------------


def test_nearest_rank_percentiles_on_known_data():
    data = list(range(1, 21))  # 1..20
    assert percentile(data, 0.50) == 10 and percentile(data, 0.95) == 19 and percentile(data, 1.0) == 20
    assert percentile([5], 0.95) == 5 and percentile([], 0.5) is None
    assert percentile([3, 1, 2], 0.50) == 2  # unsorted input


def test_summary_keeps_missing_samples_in_the_total_and_flags_a_small_n_p95():
    s = summarize([1.0, None, 3.0, 2.0], total=5)
    assert (s["n"], s["n_total"], s["min"], s["p50"], s["max"]) == (3, 5, 1.0, 2.0, 3.0)
    assert s["p95_is_max"] is True and s["p95"] == s["max"]
    assert summarize(list(range(25)))["p95_is_max"] is False
    assert "2 not within cap" in fmt(s) and "*" in fmt(s)
    assert "no sample (0/3)" == fmt(summarize([None, None, None]))


# --- LAT-01 / LAT-03 -------------------------------------------------------------------------


def test_lat_01_recovers_the_known_ingest_delay_within_one_polling_interval(tmp_path):
    r = go("LAT-01", tmp_path, ingest_delay_s=7.0)
    assert r.final == "DOCUMENTED"
    stats = extra(r)["stats"]
    assert stats["done"]["n"] == 10
    assert 7.0 <= stats["done"]["min"] and stats["done"]["max"] <= 8.0  # 1s polling: never earlier, at most one interval late
    assert stats["chunk_hit"]["p50"] == stats["done"]["p50"]  # the mock makes chunks searchable exactly when done


def test_lat_01_records_done_hit_and_add_time_for_every_sample(tmp_path):
    s = extra(go("LAT-01", tmp_path))["samples"][0]
    assert {"done", "chunk_hit", "add_ms"} <= set(s)


def test_lat_01_documents_that_miss_the_cap_are_inconclusive_not_dropped(tmp_path):
    r = go("LAT-01", tmp_path, ingest_delay_s=500.0)
    assert r.final == "INCONCLUSIVE" and "within its cap" in r.records[0]["notes"]


def test_lat_03_times_dreaming_and_the_first_memory_separately(tmp_path):
    r = go("LAT-03", tmp_path, ingest_delay_s=4.0, memory_delay_s=6.0)
    assert r.final == "DOCUMENTED"
    st = extra(r)["stats"]
    assert st["done"]["n"] == st["dreaming_done"]["n"] == st["memory_hit"]["n"] == 5
    assert 4.0 <= st["done"]["max"] <= 5.0
    assert 10.0 <= st["dreaming_done"]["min"] and st["dreaming_done"]["max"] <= 11.0
    assert st["dreaming_done"]["p50"] > st["done"]["p50"]


# --- LAT-02 ----------------------------------------------------------------------------------


def test_lat_02_reports_the_per_call_latency_not_a_wall_clock(tmp_path):
    r = go("LAT-02", tmp_path, search_ms=123.0)
    assert r.final == "DOCUMENTED"
    x = extra(r)
    assert x["cold_ms"] == 123.0
    for mode in ("chunks", "memories", "hybrid"):
        assert x["stats"][mode]["n"] == 30 and x["stats"][mode]["p50"] == 123.0 == x["stats"][mode]["max"], mode
    assert "cold 123ms" in r.records[0]["notes"]


def test_lat_02_is_skipped_when_the_provider_cannot_report_latency(tmp_path):
    clock = FakeClock()
    p = MockProvider(MockConfig(), clock)
    p.last_latency_ms = None
    r = run_test(TESTS["LAT-02"], p, runs=1, clock=clock, results_base=tmp_path, log=lambda s: None)
    assert r.final == "SKIPPED"


# --- LAT-04 ----------------------------------------------------------------------------------


def test_lat_04_records_each_document_and_each_event(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMTRUST_LAT04_CAP_S", "300")
    r = go("LAT-04", tmp_path, ingest_delay_s=5.0, dynamic_memory_delay_s=40.0)
    assert r.final == "DOCUMENTED"
    rows = extra(r)["rows"]
    assert [x["doc"] for x in rows] == ["A1", "B1", "C1", "C2", "C3"]
    for x in rows:
        assert 5.0 <= x["done"] <= 20.0  # 15s polling
        assert 45.0 <= x["dreaming_done"] <= 65.0 and x["memory_hit"] is not None


def test_lat_04_reports_not_within_cap_instead_of_inventing_a_time(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMTRUST_LAT04_CAP_S", "100")
    r = go("LAT-04", tmp_path, ingest_delay_s=5.0, dynamic_memory_delay_s=5000.0)
    rows = extra(r)["rows"]
    assert r.final == "DOCUMENTED" and all(x["memory_hit"] is None and x["dreaming_done"] is None and x["capped"] for x in rows)
    assert "memory not within cap" in r.records[0]["notes"]
    assert all(x["done"] is not None for x in rows)


def test_p95_is_labelled_the_maximum_exactly_below_twenty_samples():
    assert summarize(list(range(19)))["p95_is_max"] is True and summarize(list(range(19)))["p95"] == 18
    assert summarize(list(range(20)))["p95_is_max"] is False and summarize(list(range(20)))["p95"] == 18  # rank 19 of 20
