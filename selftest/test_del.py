"""Do the DEL tests report PASS and FAIL correctly? Each bug below must flip exactly the tests it should."""

import importlib.util
from pathlib import Path

import pytest

from src.clock import FakeClock
from src.adapter import StatusResult
from src.providers.mock import Bugs, MockConfig, MockProvider
from src.runner import run_test

_spec = importlib.util.spec_from_file_location("product_test_del", Path(__file__).parent.parent / "tests" / "test_del.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TESTS = {t.id: t for t in _mod.TESTS}


def go(test_id, tmp_path, ingest_delay_s=2.0, **bugs):
    clock = FakeClock()
    p = MockProvider(MockConfig(ingest_delay_s=ingest_delay_s, bugs=Bugs(**bugs)), clock)
    return run_test(TESTS[test_id], p, runs=3, clock=clock, results_base=tmp_path, log=lambda s: None)


@pytest.mark.parametrize("test_id", ["DEL-01", "DEL-02", "DEL-03", "DEL-04", "DEL-05"])
def test_healthy_provider_passes_every_del_test(test_id, tmp_path):
    r = go(test_id, tmp_path)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])


@pytest.mark.parametrize("test_id", ["DEL-01", "DEL-02", "DEL-03", "DEL-05"])
def test_delete_that_removes_nothing_fails(test_id, tmp_path):
    r = go(test_id, tmp_path, delete_noop=True)
    assert r.final == "FAIL" and r.per_run == ["FAIL"] * 3


@pytest.mark.parametrize("test_id, visible_for, verdict", [
    ("DEL-01", 20, "PASS"),    # gone by 30s
    ("DEL-01", 200, "SLOW"),   # present at 120s, gone by 600s
    ("DEL-01", 700, "FAIL"),   # still present at 600s
    ("DEL-02", 200, "SLOW"),
])
def test_deletion_delay_maps_to_the_pre_registered_verdicts(test_id, visible_for, verdict, tmp_path):
    assert go(test_id, tmp_path, delete_visible_for_s=visible_for).final == verdict


def test_derived_memories_surviving_the_source_delete_fail_and_name_the_surface(tmp_path):
    for test_id in ("DEL-01", "DEL-03"):  # all three search modes count (amendment A1), so DEL-01 sees it too
        r = go(test_id, tmp_path, delete_leaves_memories=True)
        note = r.records[0]["notes"]
        assert r.final == "FAIL", test_id
        assert "search:memories" in note and "search:chunks" not in note, note  # the chunk surface did go away


def test_profile_only_persistence_is_caught(tmp_path):
    # The mock keeps memories visible in both search and profile with this bug, so check the note names profile too.
    r = go("DEL-03", tmp_path, delete_leaves_memories=True)
    assert "profile" in r.records[0]["notes"]


def test_intermittent_delete_is_fail_not_inconclusive(tmp_path):
    r = go("DEL-01", tmp_path, flaky_delete_every=2)
    assert r.per_run == ["PASS", "FAIL", "PASS"] and r.final == "FAIL"


def test_content_that_reappears_after_a_first_absence_is_recorded_and_not_passed(tmp_path):
    # Gone at the first probe, back 5s later: the confirming probe must catch it.
    r = go("DEL-01", tmp_path, reappear_after_s=8)
    assert r.final == "FAIL"
    assert "reappeared" in r.records[0]["notes"]


def test_rejected_delete_while_processing_is_the_documented_pass(tmp_path):
    r = go("DEL-04", tmp_path)
    assert r.final == "PASS" and "rejected as documented" in r.records[0]["notes"]


def test_accepted_delete_while_processing_that_never_resurfaces_passes_with_a_note(tmp_path):
    r = go("DEL-04", tmp_path, delete_while_processing_ok=True)
    assert r.final == "PASS" and "accepted although the docs say it is rejected" in r.records[0]["notes"]


def test_resurrected_document_after_delete_while_processing_is_fail(tmp_path):
    r = go("DEL-04", tmp_path, delete_while_processing_ok=True, resurrect_after_processing=True)
    assert r.final == "FAIL" and "resurrected" in r.records[0]["notes"]


def test_re_add_leaving_a_ghost_of_the_old_state_is_fail(tmp_path):
    r = go("DEL-05", tmp_path, readd_ghost=True)
    assert r.final == "FAIL" and "ghost" in r.records[0]["notes"]


def test_del_04_is_skipped_when_processing_is_already_done_at_delete_time(tmp_path):
    r = go("DEL-04", tmp_path, ingest_delay_s=0.0)
    assert r.final == "SKIPPED"


def test_provider_that_never_finishes_is_error_not_a_finding(tmp_path):
    r = go("DEL-01", tmp_path, ingest_delay_s=10_000)
    assert r.final == "ERROR"


@pytest.mark.parametrize("gone_at, want", [(0, "PASS"), (120, "PASS"), (121, "SLOW"), (300, "SLOW"), (600, "SLOW"), (601, "FAIL"), (None, "FAIL")])
def test_deletion_verdict_boundaries_are_exactly_120_and_600(gone_at, want):
    from src.deletion import deletion_verdict

    assert deletion_verdict(gone_at) == want


# --- DEL-06 ----------------------------------------------------------------------------------


def test_del_06_passes_when_the_namespace_delete_really_erases_the_preserved_memory(tmp_path):
    r = go("DEL-06", tmp_path)
    assert r.final == "PASS", (r.per_run, [x["notes"] for x in r.records])
    assert "preserved before the namespace delete" in r.records[0]["notes"]


def test_del_06_fails_when_the_namespace_delete_keeps_the_data(tmp_path):
    r = go("DEL-06", tmp_path, namespace_delete_keeps_data=True)
    assert r.final == "FAIL" and r.per_run == ["FAIL"] * 3 and "+forgotten" in r.records[0]["notes"]


def test_del_06_is_inconclusive_when_the_document_delete_never_clears_the_normal_surfaces(tmp_path):
    r = go("DEL-06", tmp_path, delete_noop=True)
    assert r.final == "INCONCLUSIVE" and "DEL-03's question" in r.records[0]["notes"]


def test_del_06_is_inconclusive_when_nothing_is_preserved_to_begin_with(tmp_path):
    clock = FakeClock()
    p = MockProvider(MockConfig(forgotten_retrievable=False), clock)
    r = run_test(TESTS["DEL-06"], p, runs=3, clock=clock, results_base=tmp_path, log=lambda s: None)
    assert r.final == "INCONCLUSIVE" and "nothing for the namespace delete to remove" in r.records[0]["notes"]


def test_del_06_catches_data_that_comes_back_after_the_early_probes(tmp_path):
    # The namespace delete looks effective, then the old data returns 20s later (a restore, a lagging replica).
    r = go("DEL-06", tmp_path, namespace_data_returns_after_s=20.0)
    note = r.records[0]["notes"]
    assert r.final == "FAIL" and "t=30s" in note, note  # the 0s and 5s probes were clean; only the 30s probe caught it


class _Resurrecting(MockProvider):
    """After the namespace delete, one specific surface starts returning the old data again."""

    def __init__(self, surface, *a, **k):
        super().__init__(*a, **k)
        self.surface, self.ns_deleted = surface, False

    def delete_scope(self, scope):
        self.ns_deleted = True
        return super().delete_scope(scope)

    def profile(self, scope):
        res = super().profile(scope)
        if self.ns_deleted and self.surface == "profile":
            res.entries.append(f"Priya's pet iguana is named {self.last_token}")
        return res

    def add(self, scope, content, opts=None):
        if "iguana" in content:
            self.last_token = content.split("named ")[1].split(".")[0]
        return super().add(scope, content, opts)

    def status(self, scope, doc_id):
        if self.ns_deleted and self.surface == "document" and doc_id == self.first_id:
            return StatusResult(200, {}, "done", "done")
        return super().status(scope, doc_id)

    def delete(self, scope, doc_ids):
        self.first_id = doc_ids[0]
        return super().delete(scope, doc_ids)


def _resurrect(tmp_path, surface):
    clock = FakeClock()
    p = _Resurrecting(surface, MockConfig(), clock)
    return run_test(TESTS["DEL-06"], p, runs=1, clock=clock, results_base=tmp_path, log=lambda s: None)


def test_del_06_catches_a_profile_entry_that_returns_after_the_namespace_delete(tmp_path):
    r = _resurrect(tmp_path, "profile")
    assert r.final == "FAIL" and "via profile" in r.records[0]["notes"]


def test_del_06_catches_a_deleted_document_id_that_resolves_again(tmp_path):
    r = _resurrect(tmp_path, "document")
    assert r.final == "FAIL" and "document id still resolves" in r.records[0]["notes"]
