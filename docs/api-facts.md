# API facts (Supermemory)

Recon date: 2026-10-30. Source: `https://supermemory.ai/docs/llms.txt` and the pages linked below, read as markdown (`<url>.md`). Latest `supermemory` packages at recon time: npm **5.0.3**, PyPI **5.0.1** (memtrust uses the Python one; see `docs/sdk-notes.md`). Not run against the live API yet: everything here is what the docs say, not what the service does.

Confidence: **documented** (stated), **implied** (follows from the text, not stated), **unknown** (docs silent; the tests must find out).

Base URL: `https://api.supermemory.ai`. Docs for two API generations are live. **v5** (namespace in the URL path) is the current one; **v3/v4** (`containerTag` in the body) remains as legacy routes. memtrust targets v5 only.

## 1. Auth and keys

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Auth | `Authorization: Bearer <key>` on every request. Keys come from console.supermemory.ai, API Keys. | https://supermemory.ai/docs/authentication.md | documented |
| Scoped keys | A key can be limited to one or a list of namespaces. Requests outside the scope return `403`. Writable scoped keys can update and delete documents and forget memories. Scoped keys cannot read billing or mint keys. | https://supermemory.ai/docs/authentication.md | documented |
| Rate limit | 500 requests/minute per key by default. Over the limit returns `429` with `Retry-After` and `{code: "RATE_LIMITED", retryAfterSeconds}`. | https://supermemory.ai/docs/overview/billing.md | documented |
| Security contact | `support@supermemory.com` is named for reports, DPA and BAA. No responsible-disclosure policy page found in the index. | https://supermemory.ai/docs/overview/security.md | documented (support only); disclosure policy unknown |

## 2. Add / ingest

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Add | `POST /ns/{namespace}/document`, body `{content, id?, metadata?, dreaming?, taskType?, group?, supportingContext?, date?}`. Response `{id, status: "queued"}`. SDK: `supermemory.add(namespace, {...})`. | https://supermemory.ai/docs/ingestion/add-memories.md | documented |
| Query params | The add route accepts none; sending one returns `400`. | same | documented |
| Metadata | Flat only: string, number, boolean, or array of strings. No nested objects. | same | documented |
| Same `id` | Sending the same `id` again appends/links to the existing document and processes only new content. `documents.update` replaces content and fully reprocesses. | same; https://supermemory.ai/docs/ingestion/document-operations.md | documented |
| `dreaming` | `"dynamic"` (default) batches related docs; memories may form minutes after `status: done`; a fresh namespace can show zero memories and an empty profile for several minutes. `"instant"` dreams each doc alone, bills one extra operation. | https://supermemory.ai/docs/concepts/how-it-works.md | documented |
| `taskType` | `"memory"` (default) chunks, embeds, extracts facts, updates profile. `"superrag"` chunks and indexes only, no facts or profile. | https://supermemory.ai/docs/ingestion/add-memories.md | documented |
| File limit | 50 MB per upload. Text content size limit not stated. | same | documented (file); text limit **unknown** |
| Direct memory create | v5 has no direct create. Ingest a document with short statements and `dreaming: "instant"`. | https://supermemory.ai/docs/recall/memory-operations.md | documented |

## 3. Processing status

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Document status | `GET /ns/{namespace}/document/{id}` returns `system.status`: `queued`, `extracting`, `chunking`, `embedding`, `done`, `failed`. `done` means ready for search. `id` may be the Supermemory ID or the caller's `id`. | https://supermemory.ai/docs/ingestion/document-operations.md | documented |
| Memory status | `system.dreamingStatus`: `dreaming` or `done`. `status: done` alone does not mean memories are ready. TS SDK 5.0.1 and Python SDK 5.0.0 do not type this field; 5.0.2+ does. Use raw HTTP if unsure. | same | documented |
| Queue view | No separate processing endpoint. Use list documents and read the statuses. | same | documented |
| Expected latency | "Short chat turns usually finish in seconds"; larger PDFs and video take longer. No numeric SLA. | https://supermemory.ai/docs/concepts/how-it-works.md | documented (qualitative); numeric bound **unknown** |
| Ingest-to-search guarantee | No stated time between `status: done` and search visibility. | n/a | **unknown** |

## 4. Search

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Endpoint | `POST /ns/{namespace}/search`. Options in the JSON body only; query-string params return `400`. | https://supermemory.ai/docs/recall/search.md | documented |
| Modes | `searchMode`: `hybrid` (default, memories and chunks), `memories`, `chunks`. | same | documented |
| Scores | Every result has `similarity` (0-1), `isLatest`, `isInference`, `metadata`, `system`. Memory results carry `memory`; chunk results carry `chunk`. | same | documented |
| Threshold | `threshold` 0-1, default **0.3** (was 0.6 in v4). Higher means fewer, better results. | same | documented |
| Other options | `limit` (default 10, max 100), `rerank` (`none`/`order`/`aggregate`), `rewriteQuery`, `filter`, `include: {documents, related, forgotten}`. | same | documented |
| Forgotten memories | Search excludes forgotten and expired memories unless `include.forgotten` is set. | same | documented |
| Empty or unknown namespace | What a search returns for a namespace that has never been written to. | n/a | **unknown** |

## 5. Scoping and isolation

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Boundary | A namespace is "a hard boundary. Memories in one namespace are never returned by a search scoped to another namespace." Each namespace has a dedicated vector index; "isolation is strict rather than best-effort." | https://supermemory.ai/docs/concepts/multi-tenancy.md; https://supermemory.ai/docs/concepts/container-tags.md | documented (explicit guarantee) |
| Where it lives | v5: URL path only. One namespace per request. No multi-namespace query. | https://supermemory.ai/docs/concepts/container-tags.md | documented |
| Naming | `^[a-zA-Z0-9_:-]+$`, max 100 chars. Spaces, `/`, `@` are rejected. Opaque string, no parsing. | same | documented (rule); exact error code for violations **unknown** |
| Creation | First write auto-creates the namespace. | same | documented |
| Default namespace | `sm_project_default` exists and cannot be deleted. When it is used if none is given: unclear. | same | documented (exists); semantics **unknown** |
| No scope given | In v5 the namespace is required by the route. Legacy `/v3/search`, `/v4/search` still exist and take `containerTag`/`containerTags` in the body; behavior with none is not described. | https://supermemory.ai/docs/authentication.md | **unknown** |
| Profile | One profile per namespace; `static` and `dynamic` entries are memories from that namespace. | https://supermemory.ai/docs/recall/user-profiles.md | documented |

## 6. Deletion and forgetting

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Delete documents | `DELETE /ns/{namespace}/document` with `{ids: [...]}`, 1 to 100 per call, Supermemory or caller IDs. Permanent, no recovery. Returns `{count, errors}`; HTTP success can include per-ID failures. | https://supermemory.ai/docs/ingestion/document-operations.md | documented |
| Still processing | Only documents with status `done` or `failed` can be deleted. A processing document appears in `errors` as `Document is still processing`. | same | documented |
| Derived memories | "Memories derived from a deleted document are forgotten." | same | documented |
| Forget memories | `DELETE /ns/{namespace}/memories` with `{ids}`, 1 to 500. This is a **soft delete**: "excluded from search results but preserved." | https://supermemory.ai/docs/recall/memory-operations.md | documented |
| Forget by meaning | `DELETE /ns/{namespace}/memories/semantic` with `{query, dryRun}`; `dryRun` required; up to 100 per request. | same | documented |
| Delete namespace | `DELETE /ns/{namespace}` deletes the namespace, its memory records and documents exclusive to it; documents shared with other namespaces are retained. Needs org admin or owner. | https://supermemory.ai/docs/overview/security.md | documented |
| Delete-to-unsearchable delay | No stated delay. The docs call the delete "permanent" and say nothing about when search stops returning it. | n/a | **unknown** |
| Profile after delete | Whether profile entries from a deleted document disappear, and when. | n/a | **unknown** |
| "Erasure limits" | The namespaces page links to "deletion scope and erasure limits" on the security page, but that page lists only the namespace-delete behavior. | https://supermemory.ai/docs/concepts/container-tags.md | documented link, content thin |

## 7. Updates and corrections

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Model | Memories relate by `updates` (new fact replaces the old for search; history kept), `extends`, `derives`. `isLatest` keeps retrieval on the current fact. | https://supermemory.ai/docs/concepts/graph-memory.md | documented |
| Observable? | Yes: search results expose `isLatest`; `include.related` adds parent/child/sibling memories; list `type=memories` shows memories. | https://supermemory.ai/docs/recall/search.md | documented |
| Automatic forgetting | Time-based expiry for temporary facts; contradiction (updates win); noise filtering. | https://supermemory.ai/docs/concepts/graph-memory.md | documented |
| Retraction ("forget that I said X") | Only via explicit forget calls. Whether text in ingested content can retract a prior fact is not described. | n/a | **unknown** |
| Update memory directly | v5 has none. Update the source document; memories follow. | https://supermemory.ai/docs/recall/memory-operations.md | documented |
| Timing | Memory updates depend on dreaming; no numeric bound. | https://supermemory.ai/docs/concepts/how-it-works.md | **unknown** (numeric) |

## 8. Plan limits and cost

| Topic | What the docs say | Doc URL | Confidence |
|---|---|---|---|
| Free plan | `api_free`, 0 USD, **5 USD** of included credits per month. Memory API, search and profiles are included. Connectors, team management, restricted members and User Insights are not. | https://supermemory.ai/docs/overview/billing.md | documented |
| Rates | Memory text tokens 0.005 USD/1K; SuperRAG text 0.001 USD/1K; search 0.005 USD/1K queries; operations 0.10 USD/1K. | same | documented |
| Out of credits | `402` with a body naming the meter. Feature not in plan: `403`. | same | documented |
| Billing read | Org admin or owner can read usage; scoped keys cannot. | same | documented |

Practical read: the whole planned suite is a few thousand API calls and well under 1 USD at list rates. The binding limit is 500 requests/minute per key, not money. Credit inclusion is labeled "approximate" in the docs.

## 9. Claims that read as guarantees (to test, not assume)

1. "Memories in one namespace are never returned by a search scoped to another namespace." (multi-tenancy, container-tags)
2. "Isolation is strict rather than best-effort"; "no shared index to filter through." (container-tags)
3. "A malicious or buggy client with a correctly scoped key cannot read another namespace's memories." (security)
4. "Memories derived from a deleted document are forgotten." (document-operations)
5. "Deletes are permanent, no recovery." (document-operations)
6. "Updates win for what's true now"; `isLatest` keeps retrieval on the current fact. (graph-memory)
7. Retrieval "in the ~sub-300ms p50 range" on typical search workloads. (security; validate on your traffic shape)
8. "Your customer content is never used to train models", every plan. (security; **not testable** from outside)

## 10. Top gaps (candidate S3 DX findings, pending live confirmation)

1. **No stated delete-to-unsearchable delay.** Deletes are "permanent", but nothing says when search stops returning the content.
2. **No numeric bound on ingest-to-searchable or on dreaming.** Only "seconds" for short chat turns and "several minutes" for a fresh namespace.
3. **Soft vs hard delete is split across pages.** Document delete is permanent; memory forget is a soft delete that "preserves" the memory. The erasure-limits link points to a page that does not describe them.
4. **No disclosure policy.** Only a support email is named for security.
5. **Namespace validation and empty-namespace behavior undocumented.** Which status code a bad namespace gets, and what a search on a never-written namespace returns.

## 11. Open questions for the first live run

Resolve these in the Day-1 smoke test (excluded from results, see `decisions.md` D1):

- Does `similarity` vary enough between answerable and unanswerable queries to separate them (decides ABS)?
- Does a delete return `count: 1` and when does the canary stop appearing in `chunks`, `memories` and `hybrid` search?
- Does `dreaming: "instant"` make the memories surface reliably enough for COR?
- What does a search on a never-written namespace return?
- What status code does an invalid namespace get?

Sources read: the docs index and the pages cited above. Pages downloaded but not read in full: `quickstart`, `concepts/filtering`, `concepts/user-profiles`, `migration/api-v5*`, and the v5 OpenAPI reference pages (grepped only for delete and search). Not downloaded: `concepts/super-rag`, `concepts/rules`, `recall/memory-review`.
