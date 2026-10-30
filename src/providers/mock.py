"""In-memory provider for checking the harness itself, never the product.

Configurable delays and bugs let us confirm that the test logic reports PASS and FAIL correctly
before it touches the real API. It runs on whatever Clock it is given (FakeClock => instant).
It models the *documented* behaviour (e.g. a processing document cannot be deleted, derived memories
are forgotten with their source) when no bug is set; it says nothing about how the real service behaves.
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
    delete_leaves_memories: bool = False  # source doc goes away but derived memories / profile entries stay
    cross_namespace_leak: bool = False  # search returns docs from every scope
    prefix_scope_leak: bool = False  # search in "user_1" also returns docs from "user_10"
    delete_while_processing_ok: bool = False  # docs say this must be rejected; True = silently accepted
    resurrect_after_processing: bool = False  # a doc deleted while processing becomes searchable anyway
    readd_ghost: bool = False  # re-adding a deleted id leaves a visible duplicate of the old content
    reappear_after_s: float = 0.0  # a deleted doc is gone, then comes back this many seconds after the delete


@dataclass
class MockConfig:
    ingest_delay_s: float = 2.0  # queued -> done, and chunks searchable
    memory_delay_s: float = 1.0  # extra time after done until derived memories exist
    bugs: Bugs = field(default_factory=Bugs)


@dataclass
class _Doc:
    id: str
    content: str
    created: float
    deleted_at: float | None = None
    deleted_while_processing: bool = False


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

    def _memory_ready(self, d: _Doc) -> bool:
        return self.clock.now() - d.created >= self.config.ingest_delay_s + self.config.memory_delay_s

    def _gone(self, d: _Doc) -> bool:
        """True once a delete has taken full effect for the source document (chunks)."""
        b = self.config.bugs
        if d.deleted_at is None:
            return False
        if d.deleted_while_processing and b.resurrect_after_processing:
            return False
        age = self.clock.now() - d.deleted_at
        if b.reappear_after_s and age >= b.reappear_after_s:
            return False
        return age >= b.delete_visible_for_s

    def _chunk_visible(self, d: _Doc) -> bool:
        return self._is_done(d) and not self._gone(d)

    def _memory_visible(self, d: _Doc) -> bool:
        if not self._memory_ready(d):
            return False
        if self.config.bugs.delete_leaves_memories and d.deleted_at is not None:
            return True
        return not self._gone(d)

    def _scopes_for(self, scope: str) -> list[str]:
        b = self.config.bugs
        if b.cross_namespace_leak:
            return list(self._docs)
        if b.prefix_scope_leak:
            return [s for s in self._docs if s.startswith(scope)]
        return [scope] if scope in self._docs else []

    # --- adapter surface ---------------------------------------------------------------------

    def capabilities(self) -> Capabilities:
        return Capabilities(scores=True, threshold=True, status_endpoint=True, profiles=True, memories_surface=True, namespace_delete=True)

    def add(self, scope: str, content: str, opts: AddOptions | None = None) -> AddResult:
        o = opts or AddOptions()
        self._n += 1
        doc_id = o.id or f"doc_{self._n}"
        docs = self._docs.setdefault(scope, {})
        old = docs.get(doc_id)
        if old is not None and old.deleted_at is not None and self.config.bugs.readd_ghost:
            ghost = _Doc(f"{doc_id}~ghost", old.content, old.created)
            docs[ghost.id] = ghost
        docs[doc_id] = _Doc(doc_id, content, self.clock.now())
        body = {"id": doc_id, "status": "queued"}
        self._record("POST", f"/ns/{scope}/document", {"content": content, "id": o.id}, 200, body)
        return AddResult(200, body, doc_id)

    def search(self, scope: str, query: str, opts: SearchOptions | None = None) -> SearchResult:
        o = opts or SearchOptions()
        hits: list[SearchHit] = []
        for s in self._scopes_for(scope):
            for d in self._docs[s].values():
                if o.mode in ("chunks", "hybrid") and self._chunk_visible(d):
                    hits.append(SearchHit(id=f"chunk_{d.id}", kind="chunk", text=d.content, score=0.8, is_latest=True, is_inference=False, raw={"scope": s}))
                if o.mode in ("memories", "hybrid") and self._memory_visible(d):
                    hits.append(SearchHit(id=f"mem_{d.id}", kind="memory", text=f"Fact: {d.content}", score=0.8, is_latest=True, is_inference=False, raw={"scope": s}))
        body = {"results": [{"id": h.id, "chunk" if h.kind == "chunk" else "memory": h.text, "similarity": h.score} for h in hits]}
        self._record("POST", f"/ns/{scope}/search", {"query": query, "searchMode": o.mode}, 200, body)
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
                    d.deleted_while_processing = not self._is_done(d)
                    d.deleted_at = self.clock.now()
        body = {"count": count, "errors": errors}
        self._record("DELETE", f"/ns/{scope}/document", {"ids": doc_ids}, 200, body)
        return DeleteResult(200, body, count, errors)

    def status(self, scope: str, doc_id: str) -> StatusResult | None:
        d = self._docs.get(scope, {}).get(doc_id)
        if d is None or (d.deleted_at is not None and self._gone(d)):
            self._record("GET", f"/ns/{scope}/document/{doc_id}", None, 404, {"error": "not found"})
            return None
        state = "done" if self._is_done(d) else "queued"
        dreaming = "done" if self._memory_ready(d) else "dreaming"
        body = {"id": d.id, "system": {"status": state, "dreamingStatus": dreaming}}
        self._record("GET", f"/ns/{scope}/document/{doc_id}", None, 200, body)
        return StatusResult(200, body, state, dreaming)

    def profile(self, scope: str) -> ProfileResult:
        entries = [
            f"Fact: {d.content}"
            for s in self._scopes_for(scope)
            for d in self._docs[s].values()
            if self._memory_visible(d)
        ]
        body = {"profile": {"static": [{"id": "m", "memory": e} for e in entries], "dynamic": [], "buckets": {}}}
        self._record("POST", f"/ns/{scope}/profile", None, 200, body)
        return ProfileResult(200, body, entries)

    def delete_scope(self, scope: str) -> Outcome:
        self._docs.pop(scope, None)
        self._record("DELETE", f"/ns/{scope}", {}, 200, {"success": True})
        return Outcome(200, {"success": True})

    def drain_exchanges(self) -> list[dict[str, Any]]:
        out, self._log = self._log, []
        return out
