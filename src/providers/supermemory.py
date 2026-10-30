"""Supermemory v5 through the official `supermemory` Python SDK (5.x).

Differences from the TypeScript SDK that matter here are listed in docs/sdk-notes.md. In short:
snake_case kwargs (search_mode, task_type), errors are raised as ApiError subclasses instead of
returned, and the SDK retries by default (we turn that off so flakiness stays visible).
Raw HTTP exchanges are captured with an httpx event hook, so evidence files hold the exact wire
response, not the SDK's re-serialised model.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import httpx
from supermemory import Supermemory
from supermemory.core.api_error import ApiError
from supermemory.errors import NotFoundError, TooManyRequestsError

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
from ..recorder import Recorder

MIN_GAP_S = 0.2  # ~5 req/s, far under the documented 500/min per key
MAX_429_RETRIES = 5
TIMEOUT_S = 60.0


class SupermemoryProvider:
    name = "supermemory"

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        if not api_key:
            raise ValueError("SUPERMEMORY_API_KEY is not set")
        self._rec = Recorder()
        self._last_call = 0.0
        self._key = api_key
        self._base = (base_url or os.environ.get("SUPERMEMORY_BASE_URL") or "https://api.supermemory.ai").rstrip("/")
        http = httpx.Client(
            timeout=TIMEOUT_S,
            follow_redirects=True,
            event_hooks={"request": [self._on_request], "response": [self._on_response]},
        )
        self._http = http
        self.client = Supermemory(
            api_key=api_key,
            base_url=base_url or os.environ.get("SUPERMEMORY_BASE_URL"),  # override only for harness self-tests
            httpx_client=http,
            timeout=TIMEOUT_S,
            max_retries=0,  # the SDK default is 2; retries would hide flaky behaviour from the evidence
        )

    # --- raw capture -------------------------------------------------------------------------

    @staticmethod
    def _on_request(request: httpx.Request) -> None:
        request.extensions["memtrust_started"] = time.monotonic()

    def _on_response(self, response: httpx.Response) -> None:
        response.read()
        req = response.request
        try:
            body: Any = response.json() if response.content else None
        except ValueError:
            body = {"_non_json": response.text}
        req_body: Any = None
        if req.content:
            try:
                req_body = json.loads(req.content)
            except ValueError:
                req_body = {"_non_json": req.content.decode("utf-8", "replace")}
        started = req.extensions.get("memtrust_started", time.monotonic())
        self._rec.push(
            {
                "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                "method": req.method,
                "path": req.url.raw_path.decode(),
                "request_body": req_body,
                "http_status": response.status_code,
                "response_body": body,
                "ms": round((time.monotonic() - started) * 1000),
            }
        )

    def drain_exchanges(self) -> list[dict[str, Any]]:
        return self._rec.drain()

    # --- call plumbing -----------------------------------------------------------------------

    def _call(self, fn: Callable[[], Any]) -> tuple[Any, int, Any]:
        """Run one SDK call. Returns (parsed model or None, http status, raw body). Pacing + 429 handling live here."""
        error: ApiError | None = None
        data: Any = None
        for attempt in range(MAX_429_RETRIES + 1):
            gap = self._last_call + MIN_GAP_S - time.monotonic()
            if gap > 0:
                time.sleep(gap)
            self._last_call = time.monotonic()
            try:
                data, error = fn(), None
            except TooManyRequestsError as e:
                if attempt < MAX_429_RETRIES:
                    retry_after = float((e.headers or {}).get("retry-after", 2))
                    time.sleep(max(1.0, retry_after))
                    continue
                data, error = None, e
            except ApiError as e:
                data, error = None, e
            break
        last = self._rec.last
        status = last["http_status"] if last else (error.status_code or 0 if error else 0)
        raw = last["response_body"] if last else (error.body if error else None)
        return data, status, raw

    # --- adapter surface ---------------------------------------------------------------------

    def capabilities(self) -> Capabilities:
        return Capabilities(
            scores=True,
            threshold=True,
            status_endpoint=True,
            profiles=True,
            memories_surface=True,
            namespace_delete=True,
        )

    def add(self, scope: str, content: str, opts: AddOptions | None = None) -> AddResult:
        o = opts or AddOptions()
        kwargs: dict[str, Any] = {"content": content}
        if o.id is not None:
            kwargs["id"] = o.id
        if o.metadata is not None:
            kwargs["metadata"] = o.metadata
        if o.dreaming is not None:
            kwargs["dreaming"] = o.dreaming
        if o.task_type is not None:
            kwargs["task_type"] = o.task_type
        data, status, raw = self._call(lambda: self.client.add(scope, **kwargs))
        return AddResult(http_status=status, raw=raw, doc_id=str(data.id) if data is not None else "")

    def search(self, scope: str, query: str, opts: SearchOptions | None = None) -> SearchResult:
        o = opts or SearchOptions()
        kwargs: dict[str, Any] = {"query": query, "search_mode": o.mode}
        if o.threshold is not None:
            kwargs["threshold"] = o.threshold
        if o.limit is not None:
            kwargs["limit"] = o.limit
        include: dict[str, bool] = {}
        if o.include_forgotten:
            include["forgotten"] = True
        if o.include_related:
            include["related"] = True
        if include:
            kwargs["include"] = include
        data, status, raw = self._call(lambda: self.client.search(scope, **kwargs))
        hits: list[SearchHit] = []
        for r in (data.results if data is not None else []):
            memory = getattr(r, "memory", None)
            hits.append(
                SearchHit(
                    id=str(r.id),
                    kind="memory" if memory is not None else "chunk",
                    text=str(memory if memory is not None else (getattr(r, "chunk", None) or "")),
                    score=getattr(r, "similarity", None),
                    is_latest=getattr(r, "is_latest", None),
                    is_inference=getattr(r, "is_inference", None),
                    raw=r.model_dump(by_alias=True) if hasattr(r, "model_dump") else None,
                )
            )
        return SearchResult(http_status=status, raw=raw, hits=hits)

    def delete(self, scope: str, doc_ids: list[str]) -> DeleteResult:
        data, status, raw = self._call(lambda: self.client.documents.delete(scope, ids=doc_ids))
        if data is None:
            return DeleteResult(http_status=status, raw=raw)
        return DeleteResult(
            http_status=status,
            raw=raw,
            count=data.count,
            errors=[{"id": e.id, "error": e.error} for e in data.errors],
        )

    def status(self, scope: str, doc_id: str) -> StatusResult | None:
        data, status, raw = self._call(lambda: self.client.documents.get(scope, doc_id))
        if data is None:
            return None if status == 404 else StatusResult(http_status=status, raw=raw, status=f"http_{status}")
        sys = data.system
        return StatusResult(
            http_status=status,
            raw=raw,
            status=str(sys.status),
            dreaming_status=str(sys.dreaming_status) if getattr(sys, "dreaming_status", None) is not None else None,
        )

    def profile(self, scope: str) -> ProfileResult:
        data, status, raw = self._call(lambda: self.client.profile(scope))
        entries: list[str] = []
        if data is not None:
            entries = [f.memory for f in data.profile.static] + [f.memory for f in data.profile.dynamic]
        return ProfileResult(http_status=status, raw=raw, entries=entries)

    def forget(self, scope: str, memory_ids: list[str]) -> DeleteResult:
        """Forget memories: DELETE /ns/{ns}/memories. A soft delete (docs: excluded from search, preserved)."""
        data, status, raw = self._call(lambda: self.client.memories.forget(scope, ids=memory_ids))
        if data is None:
            return DeleteResult(http_status=status, raw=raw)
        return DeleteResult(
            http_status=status,
            raw=raw,
            count=data.count,
            errors=[{"id": getattr(e, "id", None), "error": getattr(e, "error", str(e))} for e in (data.errors or [])],
        )

    def delete_scope(self, scope: str) -> Outcome:
        _, status, raw = self._call(lambda: self.client.namespaces.delete(scope))
        return Outcome(http_status=status, raw=raw)

    def search_unscoped(self, query: str, mode: str = "hybrid", container_tag: str | None = None) -> SearchResult:
        """Legacy POST /v4/search with no containerTag (documented as optional, "to filter"). v5 has no unscoped route.
        threshold=0 so an unrelated query cannot hide results; used only for ISO-02 characterization.
        container_tag is for the positive control: the same route, scoped, must be able to see the data."""
        self._pace_only()
        resp = self._http.post(
            f"{self._base}/v4/search",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"q": query, "searchMode": mode, "threshold": 0, "limit": 20, **({"containerTag": container_tag} if container_tag else {})},
        )
        last = self._rec.last
        body = last["response_body"] if last else None
        hits: list[SearchHit] = []
        for r in (body or {}).get("results", []) if isinstance(body, dict) else []:
            text = r.get("memory") if r.get("memory") is not None else (r.get("chunk") or "")
            hits.append(SearchHit(id=str(r.get("id", "")), kind="memory" if r.get("memory") is not None else "chunk", text=str(text), score=r.get("similarity"), raw=r))
        return SearchResult(http_status=resp.status_code, raw=body, hits=hits)

    def _pace_only(self) -> None:
        gap = self._last_call + MIN_GAP_S - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        self._last_call = time.monotonic()

    # --- extras used by later tests (not part of the adapter) ---------------------------------

    def list_documents(self, scope: str, limit: int = 100) -> tuple[int, Any]:
        _, status, raw = self._call(lambda: self.client.list(scope, "documents", limit=limit))
        return status, raw

    def list_memories(self, scope: str, include_forgotten: bool = False, limit: int = 100) -> tuple[int, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if include_forgotten:
            kwargs["include"] = {"forgotten": True}
        _, status, raw = self._call(lambda: self.client.list(scope, "memories", **kwargs))
        return status, raw
