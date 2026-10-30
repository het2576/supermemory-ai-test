"""Fixtures for the product tests (the real API). Harness self-tests live in selftest/.

Run: pytest tests            (needs SUPERMEMORY_API_KEY in the environment or .env)
Each test body hands a TestDef to `check`, which runs it 3 times, saves raw evidence under
results/runs/<date>/, and maps the aggregated verdict onto pytest outcomes:
FAIL/ERROR fail the test, SKIPPED skips, everything else (PASS, SLOW, INCONCLUSIVE, DOCUMENTED) passes
with the verdict printed, because those are reported findings, not harness failures.
"""

from __future__ import annotations

import os

import pytest

from src.env import load_dotenv
from src.runner import TestDef, make_provider, run_test


@pytest.fixture(scope="session")
def provider_and_key():
    load_dotenv()
    name = os.environ.get("MEMTRUST_PROVIDER", "supermemory")
    if name == "supermemory" and not os.environ.get("SUPERMEMORY_API_KEY"):
        pytest.skip("SUPERMEMORY_API_KEY is not set; product tests need the real API")
    return make_provider(name)


@pytest.fixture
def check(provider_and_key):
    provider, key = provider_and_key

    def _check(test: TestDef, runs: int = 3):
        result = run_test(test, provider, runs=runs, api_key=key)
        if result.final in ("FAIL", "ERROR"):
            pytest.fail(f"{test.id}: {result.final} {result.per_run}", pytrace=False)
        if result.final == "SKIPPED":
            pytest.skip(f"{test.id}: surface unavailable")
        return result

    return _check
