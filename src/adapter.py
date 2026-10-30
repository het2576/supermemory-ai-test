"""Provider-agnostic surface. Tests are written against this, never against a vendor SDK.

Fields a provider does not expose stay None (and are declared in capabilities()).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

SearchMode = Literal["hybrid", "memories", "chunks"]


@dataclass
class AddOptions:
    id: str | None = None
    metadata: dict[str, Any] | None = None
    dreaming: Literal["dynamic", "instant"] | None = None
    task_type: Literal["memory", "superrag"] | None = None


@dataclass
class SearchOptions:
    mode: SearchMode = "hybrid"
    threshold: float | None = None
    limit: int | None = None
    include_forgotten: bool = False
    include_related: bool = False


@dataclass
class SearchHit:
    id: str
    kind: Literal["memory", "chunk"]
    text: str
    score: float | None = None
    is_latest: bool | None = None
    is_inference: bool | None = None
    raw: Any = None


@dataclass
class Outcome:
    """What every call returns besides its payload: the HTTP status and the raw response body."""

    http_status: int
    raw: Any


@dataclass
class AddResult(Outcome):
    doc_id: str = ""


@dataclass
class SearchResult(Outcome):
    hits: list[SearchHit] = field(default_factory=list)


@dataclass
class DeleteResult(Outcome):
    count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StatusResult(Outcome):
    status: str = ""
    dreaming_status: str | None = None


@dataclass
class ProfileResult(Outcome):
    entries: list[str] = field(default_factory=list)


@dataclass
class Capabilities:
    scores: bool = False
    threshold: bool = False
    status_endpoint: bool = False
    profiles: bool = False
    memories_surface: bool = False
    namespace_delete: bool = False


class MemoryProvider(Protocol):
    name: str

    def capabilities(self) -> Capabilities: ...

    def add(self, scope: str, content: str, opts: AddOptions | None = None) -> AddResult: ...

    def search(self, scope: str, query: str, opts: SearchOptions | None = None) -> SearchResult: ...

    def delete(self, scope: str, doc_ids: list[str]) -> DeleteResult:
        """Delete source documents. Per-id failures come back in errors; HTTP success does not imply count == len(ids)."""
        ...

    def status(self, scope: str, doc_id: str) -> StatusResult | None:
        """None when the document does not exist (or is not visible in this scope)."""
        ...

    def profile(self, scope: str) -> ProfileResult: ...

    # Optional: providers that have a way to search without naming a scope implement
    #   search_unscoped(self, query: str, mode: str = "hybrid", container_tag: str | None = None) -> SearchResult
    # Tests look it up with getattr and SKIP when it is absent.
    #
    # Optional: providers with an explicit way to forget derived memories implement
    #   forget(self, scope: str, memory_ids: list[str]) -> DeleteResult
    # (a soft delete: the memory is excluded from search but preserved).

    def delete_scope(self, scope: str) -> Outcome:
        """Remove a whole scope. Cleanup only; may need elevated credentials."""
        ...

    def drain_exchanges(self) -> list[dict[str, Any]]:
        """Raw HTTP exchanges (or mock equivalents) since the last drain, for the evidence files."""
        ...
