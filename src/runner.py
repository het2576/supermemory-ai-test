"""Usage: python -m src.runner [--only DEL-01,ISO] [--runs 3] [--provider supermemory|mock]

Discovers tests/test_*.py modules that export TESTS: list[TestDef], runs each test N times against
the provider, writes raw evidence per run and results.json for the day.
Also imported by tests/conftest.py so pytest and the CLI share one code path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from importlib import metadata

from .adapter import MemoryProvider
from .clock import Clock, RealClock
from .env import load_dotenv
from .recorder import scrub

Verdict = Literal["PASS", "FAIL", "SLOW", "INCONCLUSIVE", "DOCUMENTED", "SKIPPED", "ERROR"]


@dataclass
class RunOutcome:
    result: Verdict
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    time_to_consistency_s: float | None = None
    notes: str = ""
    extra: Any = None  # test-specific evidence kept next to the raw exchanges


@dataclass
class TestContext:
    provider: MemoryProvider
    run: int
    clock: Clock
    scopes: list[str] = field(default_factory=list)

    def track(self, scope: str) -> None:
        """Register a scope; the runner deletes it after the run, pass or fail."""
        self.scopes.append(scope)


@dataclass
class TestDef:
    __test__ = False  # not a pytest class

    id: str
    category: Literal["DEL", "ISO", "COR", "ABS", "POI", "LAT", "CON"]
    title: str
    run: Callable[[TestContext], RunOutcome]


@dataclass
class TestResult:
    test_id: str
    final: Verdict
    per_run: list[Verdict]
    records: list[dict[str, Any]]


PRIVACY = {"DEL", "ISO"}


def aggregate(category: str, runs: list[Verdict]) -> Verdict:
    """Combine per-run verdicts. Pre-registered rules: docs/guarantees-matrix.md section 2."""
    s = set(runs)
    if len(s) == 1:
        return runs[0]
    if "ERROR" in s:
        return "ERROR"
    if category in PRIVACY:
        if "FAIL" in s:
            return "FAIL"
        if "SLOW" in s:
            return "SLOW"
    return "INCONCLUSIVE"


def _sdk_version() -> str | None:
    try:
        return metadata.version("supermemory")
    except metadata.PackageNotFoundError:
        return None


def _results_dir(base: str | Path) -> Path:
    d = Path(base) / "runs" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _update_results_json(directory: Path, result: TestResult) -> None:
    path = directory / "results.json"
    data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {"date": directory.name, "records": [], "summary": []}
    data["records"] = [r for r in data["records"] if r["testId"] != result.test_id] + result.records
    data["summary"] = [s for s in data["summary"] if s["testId"] != result.test_id] + [
        {"testId": result.test_id, "final": result.final, "perRun": result.per_run}
    ]
    path.write_text(json.dumps(data, indent=2))


def run_test(
    test: TestDef,
    provider: MemoryProvider,
    *,
    runs: int = 3,
    api_key: str = "",
    clock: Clock | None = None,
    results_base: str | Path = "results",
    log: Callable[[str], None] = print,
) -> TestResult:
    clock = clock or RealClock()
    directory = _results_dir(results_base)
    records: list[dict[str, Any]] = []
    per_run: list[Verdict] = []

    for run in range(1, runs + 1):
        ctx = TestContext(provider=provider, run=run, clock=clock)
        try:
            outcome = test.run(ctx)
        except Exception as e:  # harness failure, not a product finding
            outcome = RunOutcome("ERROR", notes=f"harness error: {type(e).__name__}: {e}")
        for scope in ctx.scopes:
            try:
                provider.delete_scope(scope)
            except Exception:
                pass  # best-effort cleanup; any exchange was already recorded

        file = directory / f"{test.id}-run{run}.json"
        record = {
            "testId": test.id,
            "provider": provider.name,
            "client": "supermemory-python-sdk" if provider.name == "supermemory" else provider.name,
            "sdkVersion": _sdk_version() if provider.name == "supermemory" else None,
            "apiVersion": "v5",
            "date": datetime.now(timezone.utc).isoformat(),
            "run": run,
            "checkpoints": outcome.checkpoints,
            "result": outcome.result,
            "timeToConsistencySec": outcome.time_to_consistency_s,
            "notes": outcome.notes,
            "rawArtifacts": file.as_posix(),
        }
        payload = scrub({"record": record, "extra": outcome.extra, "exchanges": provider.drain_exchanges()}, [api_key])
        file.write_text(json.dumps(payload, indent=2, default=str))
        records.append(record)
        per_run.append(outcome.result)
        log(f"{test.id} run {run}: {outcome.result}" + (f"  ({outcome.notes})" if outcome.notes else ""))

    result = TestResult(test.id, aggregate(test.category, per_run), per_run, records)
    _update_results_json(directory, result)
    log(f"{test.id} => {result.final}  [{', '.join(per_run)}]")
    return result


def make_provider(name: str) -> tuple[MemoryProvider, str]:
    if name == "mock":
        from .providers.mock import MockProvider

        return MockProvider(), ""
    from .providers.supermemory import SupermemoryProvider

    key = os.environ.get("SUPERMEMORY_API_KEY", "")
    return SupermemoryProvider(key), key


def discover_tests(root: str | Path = "tests") -> list[TestDef]:
    found: list[TestDef] = []
    for f in sorted(Path(root).glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(f.stem, f)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        found.extend(getattr(mod, "TESTS", []))
    return sorted(found, key=lambda t: t.id)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated test id prefixes, e.g. DEL-01,ISO")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--provider", default="supermemory", choices=["supermemory", "mock"])
    args = ap.parse_args()

    tests = discover_tests()
    if args.only:
        wanted = [w.strip().upper() for w in args.only.split(",")]
        tests = [t for t in tests if any(t.id.startswith(w) for w in wanted)]
    if not tests:
        print("No tests found. Add tests/test_<category>.py exporting TESTS.")
        return
    provider, key = make_provider(args.provider)
    for t in tests:
        run_test(t, provider, runs=args.runs, api_key=key)


if __name__ == "__main__":
    main()
