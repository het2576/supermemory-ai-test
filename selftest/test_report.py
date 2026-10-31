"""The report generator must reproduce known numbers from synthetic evidence, and never touch text outside its markers."""

import json
from pathlib import Path

from src import report


def run_file(day: Path, tid: str, n: int, result: str, extra=None, ttc=None, checkpoints=None, notes="") -> Path:
    f = day / f"{tid}-run{n}.json"
    rec = {"testId": tid, "result": result, "timeToConsistencySec": ttc, "notes": notes, "checkpoints": checkpoints or [], "rawArtifacts": f.as_posix()}
    f.write_text(json.dumps({"record": rec, "extra": extra, "exchanges": []}))
    return f


def make_results(tmp_path: Path) -> Path:
    results = tmp_path / "results"
    day = results / "runs" / "2026-10-30"
    day.mkdir(parents=True)
    summary = []
    for n in (1, 2, 3):
        run_file(day, "DEL-01", n, "PASS", ttc=0.0)
        run_file(day, "ISO-01", n, "PASS", checkpoints=[{"t": 0, "leaks": []}, {"t": 5, "leaks": []}])
        # LAT-01: three runs of two samples each; done = 10/20/30/40/50/60, hit = done - 2
        done = [10.0 * (2 * (n - 1) + i + 1) for i in range(2)]
        run_file(day, "LAT-01", n, "DOCUMENTED", extra={"samples": [{"done": d, "chunk_hit": d - 2, "add_ms": 1000.0 + d} for d in done]})
    summary += [{"testId": t, "final": "PASS", "perRun": ["PASS"] * 3} for t in ("ISO-01", "DEL-01")]
    summary += [{"testId": "LAT-01", "final": "DOCUMENTED", "perRun": ["DOCUMENTED"] * 3}]
    (day / "results.json").write_text(json.dumps({"date": "2026-10-30", "records": [], "summary": summary}))
    (results / "superseded" / "X-first-attempt").mkdir(parents=True)
    (results / "superseded" / "X-first-attempt" / "README.md").write_text("It failed\nwith a network error.")
    return results


def test_summary_is_sorted_has_counts_details_and_links_to_each_run_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = report.load(make_results(tmp_path))
    text = report.block_summary(data, tmp_path)
    ids = [line.split("|")[1].strip() for line in text.splitlines()[2:]]
    assert ids == ["DEL-01", "ISO-01", "LAT-01"]  # sorted regardless of the order they were recorded in
    assert "3/3 PASS" in text and "gone by 0s in every run" in text and "0 foreign items in 6 probes" in text
    assert "(results/runs/2026-10-30/DEL-01-run3.json)" in text and "numbers only, see the tables below" in text


def test_lat_block_pools_the_runs_with_nearest_rank_percentiles(tmp_path):
    data = report.load(make_results(tmp_path))
    text = report.block_lat(data, tmp_path)
    done_row = next(line for line in text.splitlines() if "Ingest (default dreaming): `status: done`" in line)
    # six samples 10,20,...,60: p50 = rank ceil(3) = 30, p95 = rank 6 = 60 = max, flagged because n < 20
    assert "| 30.0s | 60.0s* | 60.0s | 6 |" in done_row
    hit_row = next(line for line in text.splitlines() if "first chunk-search hit" in line)
    assert "| 28.0s | 58.0s* | 58.0s | 6 |" in hit_row
    assert "6 of 6 documents (median gap 2.0s)" in text


def test_a_missing_category_is_stated_not_invented(tmp_path):
    data = report.load(make_results(tmp_path))
    assert "has not been run" in report.block_abs(data, tmp_path) and "has not been run" in report.block_poi(data, tmp_path)


def test_superseded_block_lists_each_attempt_with_its_reason(tmp_path):
    out = report.block_superseded(make_results(tmp_path), tmp_path)
    assert "X-first-attempt" in out and "It failed with a network error." in out


def test_poi_block_counts_forms_over_runs_and_lists_unexpected_fields(tmp_path):
    results = make_results(tmp_path)
    day = results / "runs" / "2026-10-30"

    def surf(form, cues=(), marked=False, extra=()):
        return {"form": form, "cues_kept": list(cues), "marked_in_text": marked, "extra_fields": list(extra)}

    for n, mem in enumerate(("absent", "absent", "rewritten"), 1):
        run_file(day, "POI-01", n, "DOCUMENTED", extra={"reports": {"instruction": {"chunks": surf("verbatim"), "memories": surf(mem, extra=["provenance"] if n == 3 else [])}}})
    rj = json.loads((day / "results.json").read_text())
    rj["summary"].append({"testId": "POI-01", "final": "DOCUMENTED", "perRun": ["DOCUMENTED"] * 3})
    (day / "results.json").write_text(json.dumps(rj))  # a test counts only once it has finished all its runs
    text = report.block_poi(report.load(results), tmp_path)
    assert "| POI-01 instruction | chunks | verbatim 3/3 | - | 0/3 | none |" in text
    assert "| POI-01 instruction | memories | absent 2/3, rewritten 1/3 | - | 0/3 | provenance |" in text


def test_write_into_replaces_only_the_marked_blocks(tmp_path):
    f = tmp_path / "REPORT.md"
    f.write_text("intro text stays\n<!-- BEGIN:lat -->\nOLD\n<!-- END:lat -->\nmiddle stays\n<!-- BEGIN:unknown -->\nkeep\n<!-- END:unknown -->\noutro stays\n")
    done = report.write_into(f, {"lat": "NEW TABLE", "poi": "ignored: no marker for it"})
    text = f.read_text()
    assert done == ["lat"] and "NEW TABLE" in text and "OLD" not in text
    assert "intro text stays" in text and "middle stays" in text and "keep" in text and "outro stays" in text and "ignored" not in text


def test_mixed_verdicts_are_listed_not_summarised_as_uniform():
    assert report._runs(["PASS", "PASS", "PASS"]) == "3/3 PASS"
    assert report._runs(["PASS", "FAIL", "PASS"]) == "PASS FAIL PASS"
    assert report._runs(["DOCUMENTED"]) == "1/1 DOCUMENTED"


def test_the_gap_between_searchable_and_done_is_a_median_not_a_maximum(tmp_path):
    results = tmp_path / "results"
    day = results / "runs" / "2026-10-30"
    day.mkdir(parents=True)
    samples = [{"done": 10.0, "chunk_hit": 9.0, "add_ms": 1.0}, {"done": 10.0, "chunk_hit": 8.0, "add_ms": 1.0}, {"done": 10.0, "chunk_hit": 1.0, "add_ms": 1.0}]
    run_file(day, "LAT-01", 1, "DOCUMENTED", extra={"samples": samples})
    (day / "results.json").write_text(json.dumps({"date": "x", "records": [], "summary": [{"testId": "LAT-01", "final": "DOCUMENTED", "perRun": ["DOCUMENTED"]}]}))
    text = report.block_lat(report.load(results), tmp_path)
    assert "3 of 3 documents (median gap 2.0s)" in text  # gaps are 1, 2 and 9


def test_results_from_several_days_are_merged_and_a_rerun_takes_the_latest_day(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = make_results(tmp_path)  # day 2026-10-30 has DEL-01, ISO-01, LAT-01
    day2 = results / "runs" / "2026-10-31"
    day2.mkdir()
    run_file(day2, "POI-02", 1, "DOCUMENTED")
    run_file(day2, "DEL-01", 1, "FAIL", ttc=None, notes="rerun")  # DEL-01 rerun on the next day: only this one counts
    (day2 / "results.json").write_text(json.dumps({"date": "2026-10-31", "records": [], "summary": [
        {"testId": "POI-02", "final": "DOCUMENTED", "perRun": ["DOCUMENTED"]}, {"testId": "DEL-01", "final": "FAIL", "perRun": ["FAIL"]}]}))
    data = report.load(results)
    by_id = {s["testId"]: s for s in data["summary"]}
    assert set(by_id) == {"DEL-01", "ISO-01", "LAT-01", "POI-02"}  # nothing from the first day was dropped
    assert by_id["DEL-01"]["final"] == "FAIL" and len(data["files"]["DEL-01"]) == 1 and "2026-10-31" in data["files"]["DEL-01"][0].as_posix()
    assert len(data["files"]["ISO-01"]) == 3 and "2026-10-30" in data["files"]["ISO-01"][0].as_posix()


def test_a_test_that_never_finished_is_left_out_not_half_reported(tmp_path):
    results = make_results(tmp_path)
    run_file(results / "runs" / "2026-10-30", "POI-02", 1, "DOCUMENTED")  # run file exists, but no summary entry: interrupted
    data = report.load(results)
    assert "POI-02" not in data["files"] and "POI-02" not in [s["testId"] for s in data["summary"]]
