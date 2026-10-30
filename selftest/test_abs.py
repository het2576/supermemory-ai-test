"""Do the ABS tests recover known score distributions and threshold behavior from the mock?"""

import importlib.util
import zlib
import json
from pathlib import Path

import pytest

from src.abstention import auc, best_threshold, class_summary, gap, reliably_removes_junk, separation
from src.clock import FakeClock
from src.providers.mock import Bugs, MockConfig, MockProvider
from src.runner import run_test

_spec = importlib.util.spec_from_file_location("product_test_abs", Path(__file__).parent.parent / "tests" / "test_abs.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TESTS = {t.id: t for t in _mod.TESTS}
MARKERS = _mod.MARKERS


def clean_scorer(query, text):
    """Answerable query + its fact => 0.8; everything else 0.2 (below the 0.3 default): perfectly separable."""
    m = MARKERS.get(query)
    return 0.8 if m and m.lower() in text.lower() else 0.2


def overlapping_scorer(query, text):
    """Near-miss and off-domain queries match anything at 0.5 to 0.7; answerable facts score 0.55 to 0.8: ranges overlap."""
    m = MARKERS.get(query)
    if m:
        return 0.55 + 0.25 * (zlib.crc32(m.encode()) % 100) / 100 if m.lower() in text.lower() else 0.2
    return 0.5 + 0.2 * (zlib.crc32(query.encode()) % 100) / 100


def constant_scorer(query, text):
    return 0.8


def go(test_id, tmp_path, scorer=clean_scorer, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(scorer=scorer, bugs=Bugs(**bugs)), clock)
    return p, run_test(TESTS[test_id], p, runs=1, clock=clock, results_base=tmp_path, log=lambda s: None)


def summary(result):
    return json.loads(Path(result.records[0]["rawArtifacts"]).read_text())["extra"]["summary"]


# --- statistics on known data ----------------------------------------------------------------


def test_auc_gap_and_best_threshold_on_known_data():
    a, u = [0.8, 0.7, 0.9], [0.2, 0.3, None]
    assert auc(a, u) == 1.0 and gap(a, u) == pytest.approx(0.4) and separation(a, u)["separable"] is True
    assert best_threshold(a, u)["balanced_accuracy"] == 1.0
    overlap = separation([0.8, 0.5], [0.6, 0.2])
    assert overlap["separable"] is False and overlap["gap"] == pytest.approx(-0.1) and overlap["auc"] == 0.75


def test_ties_count_half_and_an_empty_result_ranks_below_any_score():
    assert auc([0.5], [0.5]) == 0.5
    assert auc([None], [0.1]) == 0.0 and auc([0.1], [None]) == 1.0  # nothing returned carries no evidence
    assert separation([0.5, None], [0.1])["separable"] is False  # an answerable query with no result breaks separation


def test_class_summary_counts_empty_results_without_polluting_the_scores():
    s = class_summary([0.2, None, 0.6, None])
    assert (s["n"], s["empty"], s["min"], s["max"]) == (4, 2, 0.2, 0.6)


def test_reading_rule_for_a_threshold_that_reliably_removes_junk():
    good = [{"unanswerable_any": 0, "answerable_correct": 0.95}] * 3
    assert reliably_removes_junk(good, baseline_kept=1.0) is True
    assert reliably_removes_junk(good + [{"unanswerable_any": 1, "answerable_correct": 1.0}], 1.0) is False  # one stray result in one run
    assert reliably_removes_junk([{"unanswerable_any": 0, "answerable_correct": 0.8}], 1.0) is False  # lost too many answers
    assert reliably_removes_junk([], 1.0) is False


# --- ABS-01 / ABS-02 -------------------------------------------------------------------------


def test_abs_01_recovers_a_perfectly_separable_distribution(tmp_path):
    _, r = go("ABS-01", tmp_path)
    assert r.final == "DOCUMENTED"
    sep = summary(r)["hybrid"]["separation"]
    assert sep["auc"] == 1.0 and sep["separable"] is True and sep["gap"] == pytest.approx(0.6)
    assert summary(r)["hybrid_default_nonempty"] == {"near_miss": 0}  # junk (0.2) is under the documented default of 0.3


def test_abs_01_constant_scores_give_no_separation_and_junk_at_the_default(tmp_path):
    _, r = go("ABS-01", tmp_path, scorer=constant_scorer)
    s = summary(r)
    assert s["hybrid"]["separation"]["auc"] == 0.5 and s["hybrid"]["separation"]["separable"] is False
    assert s["hybrid_default_nonempty"] == {"near_miss": 20}


def test_abs_01_overlapping_ranges_are_reported_as_overlap(tmp_path):
    _, r = go("ABS-01", tmp_path, scorer=overlapping_scorer)
    sep = summary(r)["hybrid"]["separation"]
    assert sep["separable"] is False and 0.0 < sep["auc"] < 1.0 and sep["best"]["balanced_accuracy"] < 1.0


def test_abs_02_counts_unanswerable_results_at_the_default_per_class(tmp_path):
    _, r = go("ABS-02", tmp_path)
    assert summary(r)["hybrid_default_nonempty"] == {"off_domain": 0, "nonsense": 0}
    _, r = go("ABS-02", tmp_path, scorer=constant_scorer)
    assert summary(r)["hybrid_default_nonempty"] == {"off_domain": 10, "nonsense": 5}


def test_an_unusable_seed_is_inconclusive_not_a_distribution(tmp_path):
    _, r = go("ABS-01", tmp_path, scorer=lambda q, t: -0.5)  # nothing survives even threshold 0
    assert r.final == "INCONCLUSIVE" and "seed is not usable" in r.records[0]["notes"]


def test_abs_is_skipped_when_the_provider_has_no_scores(tmp_path):
    clock = FakeClock()
    p = MockProvider(MockConfig(), clock)
    real = p.capabilities()
    real.scores = False
    p.capabilities = lambda: real
    r = run_test(TESTS["ABS-01"], p, runs=1, clock=clock, results_base=tmp_path, log=lambda s: None)
    assert r.final == "SKIPPED" and "no abstention signal" in r.records[0]["notes"]


# --- ABS-03 ----------------------------------------------------------------------------------


def test_abs_03_sweep_shows_the_threshold_removing_junk_when_scores_separate(tmp_path):
    _, r = go("ABS-03", tmp_path)
    sw = summary(r)["sweep"]
    assert sw["0"]["unanswerable_any"] > 0  # threshold 0 lets everything through
    for t in ("omitted", "0.3", "0.5", "0.8"):
        assert sw[t]["unanswerable_any"] == 0 and sw[t]["answerable_correct"] == 1.0, t
    assert summary(r)["omitted_equals_0.3"] is True
    assert set(summary(r)["server_filter_equals_client_filter"].values()) == {"55/55"}


def test_abs_03_shows_the_trade_off_when_scores_overlap(tmp_path):
    _, r = go("ABS-03", tmp_path, scorer=overlapping_scorer)
    sw = summary(r)["sweep"]
    assert sw["0.5"]["unanswerable_any"] > 0  # junk survives a mid threshold
    assert sw["0.8"]["answerable_correct"] < 1.0  # and a high one costs answers
    assert sw["0.8"]["unanswerable_any"] <= sw["0.5"]["unanswerable_any"]


def test_a_threshold_parameter_that_does_nothing_is_visible_in_the_sweep(tmp_path):
    _, r = go("ABS-03", tmp_path, ignore_threshold=True)
    sw = summary(r)["sweep"]
    assert sw["0.8"]["unanswerable_any"] == sw["0"]["unanswerable_any"] > 0
    assert any(v != "55/55" for v in summary(r)["server_filter_equals_client_filter"].values())


def wrong_fact_scorer(query, text):
    """The right fact scores 0.1; every other fact scores 0.8: results come back, but never the correct one."""
    m = MARKERS.get(query)
    return 0.1 if m and m.lower() in text.lower() else 0.8


def test_a_score_equal_to_the_threshold_is_kept_not_removed():
    # The server keeps similarity >= t, so an unanswerable score of exactly t is NOT removed by threshold t.
    best = best_threshold([0.8, 0.5], [0.5])
    assert best["threshold"] == 0.8 and best["balanced_accuracy"] == 0.75


def test_abs_03_distinguishes_a_result_coming_back_from_the_correct_fact_coming_back(tmp_path):
    _, r = go("ABS-03", tmp_path, scorer=wrong_fact_scorer)
    sw = summary(r)["sweep"]
    assert sw["0"]["answerable_correct"] == 1.0  # at threshold 0 the right fact is in the results
    assert sw["0.3"]["answerable_any"] == 1.0 and sw["0.3"]["answerable_correct"] == 0.0  # above it, only wrong facts
