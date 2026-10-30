# Python SDK notes (supermemory 5.0.1)

Inspected 2026-10-30 from the installed package source (`.venv/lib/python3.12/site-packages/supermemory/`), not from memory. PyPI latest at that time: **5.0.1** (the npm TypeScript SDK was at 5.0.3). Pinned in `requirements.txt`.

## Methods the provider uses

| Adapter call | Python SDK call | Returns |
|---|---|---|
| `add` | `client.add(namespace, *, content, id=, metadata=, task_type=, dreaming=, ...)` | `DocumentRef` (`id`, `status`) |
| `search` | `client.search(namespace, *, query, search_mode=, threshold=, limit=, include=, filter=, rerank=, rewrite_query=)` | `SearchResponse` (`results[]`, `search_time`) |
| `delete` | `client.documents.delete(namespace, *, ids=[...])` | `DeleteDocumentsResult` (`count`, `errors[{id, error}]`) |
| `status` | `client.documents.get(namespace, id, *, include=)` | `Document` (`system.status`, `system.dreaming_status`) |
| `profile` | `client.profile(namespace, *, filter=, buckets=)` | `ProfileResponse` (`profile.static`, `.dynamic`, `.buckets`) |
| `delete_scope` | `client.namespaces.delete(namespace, *, move_to=None)` | `NamespaceDeleted` |
| list (extras) | `client.list(namespace, type, *, page=, limit=, include=, ...)` with `type` of `documents`, `chunks`, `memories` | `ListResponse` |
| forget (later) | `client.memories.forget(namespace, *, ids=[...])`, `client.memories.forget_matching(...)` | `ForgetResult` |

Every method also has `extra_headers`, `extra_query`, `extra_body`, `timeout`, `request_options`. All call shapes above match the REST routes in `docs/api-facts.md`; nothing was invented.

## What differs from the TypeScript SDK and from the docs

1. **snake_case parameters.** `search_mode`, `task_type`, `rewrite_query`, `supporting_context`, `move_to`. Response models use snake_case attributes with camelCase wire aliases (`is_latest` for `isLatest`, `dreaming_status` for `dreamingStatus`, `search_time` for `searchTime`).
2. **Errors are raised, not returned.** Non-2xx responses raise `ApiError` subclasses (`NotFoundError`, `BadRequestError`, `ForbiddenError`, `PaymentRequiredError`, `TooManyRequestsError`, ...), each carrying `status_code`, `headers` and `body`. The provider catches them so tests can assert on status codes (e.g. a 404 for a deleted document).
3. **Retries are on by default.** `max_retries` defaults to 2 and `timeout` to 60s. memtrust sets `max_retries=0` and handles 429 itself (honoring `Retry-After`, up to 5 times), because automatic retries would hide intermittent behavior from the evidence.
4. **`api_key` default is read at import time** from `SUPERMEMORY_API_KEY`. The provider always passes the key explicitly.
5. **`dreaming_status` is typed in Python 5.0.1.** The docs say Python SDK 5.0.0 does not expose it and TypeScript needs 5.0.2. In 5.0.1 it is present on `DocumentSystem` (`Literal["dreaming", "done"]`), so no raw-HTTP workaround is needed.
6. **Status enum is wider than the docs list.** The SDK type for `system.status` is `unknown | queued | extracting | chunking | embedding | indexing | done | failed`. The status table in the docs lists six values and omits `indexing` and `unknown`. Tests treat anything other than `done` or `failed` as in progress, as the docs advise.
7. **Models tolerate unexpected data.** Response models are `UncheckedBaseModel` with `extra="allow"`; a field the SDK does not know about does not raise. Good for robustness, but it means a type mismatch will not fail loudly. This is why raw responses are captured separately.
8. **Search results are one model for both kinds.** `SearchResult` has optional `memory` and `chunk`; the adapter sets `kind` from which is present.
9. **Raw responses.** The SDK has `client.with_raw_response`, but memtrust instead attaches an httpx event hook to the client it hands the SDK. That records the exact request body, status and response JSON of every call (headers are never stored, so the key cannot leak) and keeps the normal typed API for the tests.

## Not verified yet (needs the live API)

- That `client.documents.get` on a deleted document raises `NotFoundError` (404) rather than another code.
- The error type and status for an invalid namespace (`user 1`, `user/1`).
- That `client.namespaces.delete` works with a free-plan key (docs say it needs org admin or owner).
- Whether `list(..., "memories", include={"forgotten": True})` returns the shape the docs describe.
