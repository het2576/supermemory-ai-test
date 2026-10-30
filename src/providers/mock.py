"""In-memory provider for checking the harness itself, never the product.

Configurable delays and bugs let us confirm that the test logic reports PASS and FAIL correctly
before it touches the real API. It runs on whatever Clock it is given (FakeClock => instant).
It models the *documented* behaviour (e.g. a processing document cannot be deleted) when no bug is set;
it says nothing about how the real service behaves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..adapter import (
    AddOptions,
    AddResult,
    Capabilities,
    DeleteResult,
    Outcome,
    ProfileResult,
    SearchHit,
    SearchOptions,
    SearchResult,
    StatusResult,
)
from ..clock import Clock, RealClock


@dataclass
class Bugs:
    delete_noop: bool = False  # delete reports count=1 but removes nothing
    flaky_delete_every: int = 0  # every Nth delete call is a silent no-op (0 = never)
    delete_visible_for_s: float = 0.0  # deleted doc stays searchable this long (a delay; a bug only if huge)
    cross_namespace_leak: bool = False  # search returns docs from every scope
    prefix_scope_leak: bool = False  # search in "user_1" also returns docs from "user_10"
    delete_while_processing_ok: bool = False  # docs say this must be rejected; True = silently accepted


@dataclass
class MockConfig:
    ingest_delay_s: float = 2.0  # queued -> done, and searchable
    bugs: Bugs = field(default_factory=Bugs)


@dataclass
class _Doc:
    id: str
    content: str
    created: float
    deleted_at: float | None = None


class MockProvider:
    name = "mock"

    def __init__(self, config: MockConfig | None = None, clock: Clock | None = None) -> None:
        self.config = config or MockConfig()
        self.clock = clock or RealClock()
        self._docs: dict[str, dict[str, _Doc]] = {}
        self._n = 0
        self._deletes = 0
        self._log: list[dict[str, Any]] = []

    # --- helpers -----------------------------------------------------------------------------

    def _record(self, method: str, path: str, req: Any, status: int, body: Any) -> None:
        self._log.append(
            {"t": self.clock.now(), "method": method, "path": path, "request_body": req, "http_status": status, "response_body": body, "ms": 0}
        )

    def _is_done(self, d: _Doc) -> bool:
        return self.clock.now() - d.created >= self.config.ingest_delay_s

    def _visible(self, d: _Doc) -> bool:
        if not self._is_done(d):
            return False
        if d.deleted_at is None:
            return True
        return self.clock.now() - d.deleted_at < self.config.bugs.delete_visible_for_s

    def _scopes_for(self, scope: str) -> list[str]:
        b = self.config.bugs
        if b.cross_namespace_leak:
            return list(self._docs)
        if b.prefix_scope_leak:
            return [s for s in self._docs if s.startswith(scope)]
        return [scope] if scope in self._docs else []

    # --- adapter surface ---------------------------------------------------------------------

    def capabilities(self) -> Capabilities:
        return Capabilities(scores=True, threshold=True, status_endpoint=True, profiles=True, memories_surface=False, namespace_delete=True)

    def add(self, scope: str, content: str, opts: AddOptions | None = None) -> AddResult:
        o = opts or AddOptions()
        self._n += 1
        doc_id = o.id or f"doc_{self._n}"
        self._docs.setdefault(scope, {})[doc_id] = _Doc(doc_id, content, self.clock.now())
        body = {"id": doc_id, "status": "queued"}
        self._record("POST", f"/ns/{scope}/document", {"content": content}, 200, body)
        return AddResult(200, body, doc_id)

    def search(self, scope: str, query: str, opts: SearchOptions | None = None) -> SearchResult:
        hits: list[SearchHit] = []
        for s in self._scopes_for(scope):
            for d in self._docs[s].values():
                if self._visible(d):
                    hits.append(SearchHit(id=f"chunk_{d.id}", kind="chunk", text=d.content, score=0.8, is_latest=True, is_inference=False, raw={"scope": s}))
        body = {"results": [{"id": h.id, "chunk": h.text, "similarity": h.score} for h in hits]}
        self._record("POST", f"/ns/{scope}/search", {"query": query}, 200, body)
        return SearchResult(200, body, hits)

    def delete(self, scope: str, doc_ids: list[str]) -> DeleteResult:
        b = self.config.bugs
        self._deletes += 1
        flaky = b.flaky_delete_every > 0 and self._deletes % b.flaky_delete_every == 0
        count, errors = 0, []
        for doc_id in doc_ids:
            d = self._docs.get(scope, {}).get(doc_id)
            if d is None or (d.deleted_at is not None and not b.delete_noop):
                errors.append({"id": doc_id, "error": "not found"})
            elif not self._is_done(d) and not b.delete_while_processing_ok:
                errors.append({"id": doc_id, "error": "Document is still processing"})
            else:
                count += 1
                if not (b.delete_noop or flaky):
                    d.deleted_at = self.clock.now()
        body = {"count": count, "errors": errors}
        self._record("DELETE", f"/ns/{scope}/document", {"ids": doc_ids}, 200, body)
        return DeleteResult(200, body, count, errors)

    def status(self, scope: str, doc_id: str) -> StatusResult | None:
        d = self._docs.get(scope, {}).get(doc_id)
        if d is None or (d.deleted_at is not None and not self._visible(d) and d.deleted_at is not None):
            self._record("GET", f"/ns/{scope}/document/{doc_id}", None, 404, {"error": "not found"})
            return None
        state = "done" if self._is_done(d) else "queued"
        body = {"id": d.id, "system": {"status": state, "dreamingStatus": "done"}}
        self._record("GET", f"/ns/{scope}/document/{doc_id}", None, 200, body)
        return StatusResult(200, body, state, "done")

    def profile(self, scope: str) -> ProfileResult:
        body = {"profile": {"static": [], "dynamic": [], "buckets": {}}}
        self._record("POST", f"/ns/{scope}/profile", None, 200, body)
        return ProfileResult(200, body, [])

    def delete_scope(self, scope: str) -> Outcome:
        self._docs.pop(scope, None)
        self._record("DELETE", f"/ns/{scope}", {}, 200, {"success": True})
        return Outcome(200, {"success": True})

    def drain_exchanges(self) -> list[dict[str, Any]]:
        out, self._log = self._log, []
        return out
