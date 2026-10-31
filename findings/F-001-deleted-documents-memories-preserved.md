# F-001: memories derived from a deleted document are preserved and still returned by `include.forgotten`; the docs word this four different ways

**Status: final for this setup.** DEL-03 (3 runs) and the namespace-delete control DEL-06 (3 runs) are done.
**Severity (PRD section 10): S3** (documentation), **privacy-relevant**. It is not an S1 defect: the control showed that deleting the namespace removes the preserved memories as far as the API can show (see below), and other tenants never saw them (ISO).
**Novelty:** two searches of GitHub on 2026-10-31 found no issue in `supermemoryai/supermemory` about this. That is "I found none", not "none exists".

## What was observed

1. A document containing a fact is added (`dreaming: "instant"`); a memory carrying the fact's unique token appears.
2. The document is deleted (`DELETE /ns/{ns}/document`, response `count: 1, errors: []`).
3. At the first probe, 0 seconds later, the token is gone from `chunks`, `memories` and `hybrid` search and from the profile, and stays gone on a probe 10 seconds later. **Deletion of the document is immediate by every normal surface** (DEL-03, 3 of 3 PASS).
4. But a search with `include: {forgotten: true}` still returns the derived memory in `memories` mode, **in 6 of 6 runs** (DEL-03 3 of 3, DEL-06 3 of 3), and in `hybrid` mode in the 3 DEL-06 runs (DEL-03 only tried `memories`). The returned item has `isLatest: false`.

## What the docs say

| Where | Statement | Reading |
|---|---|---|
| Document operations ([docs](https://supermemory.ai/docs/ingestion/document-operations.md)) | Delete is "permanent, no recovery". "Memories derived from a deleted document are forgotten." | "forgotten" is a defined term, see next row |
| Memory operations ([docs](https://supermemory.ai/docs/recall/memory-operations.md)) | Forget is a soft delete: "Forgotten memories are excluded from search results but preserved." The page does not mention `include.forgotten` or any way to retrieve them. | preserved, not erased |
| API reference, delete documents ([docs](https://supermemory.ai/docs/v5/api-reference/content-management/delete-documents)) | "Permanently remove documents and their derived knowledge." | reads as erased |
| Security page ([docs](https://supermemory.ai/docs/overview/security.md)) | For a user's deletion request: "use `DELETE /ns/{namespace}` with an org admin or owner credential"; the endpoint "deletes the namespace, its namespace-owned memory records, and documents exclusive to it". Erasure limits and retention: not described. | the documented erasure route is the namespace delete, which DEL-06 verified |
| Supermemory blog, memory lifecycle ([post](https://supermemory.ai/blog/memory-lifecycle-retention-corrections-deletion/)) | "forgetting is not permanent erasure"; "Search can explicitly include forgotten entries through `include.forgottenMemories`." | preserved and retrievable; flag spelled differently from the SDK/API |

Taken together the behavior is consistent with the docs if "forgotten" is read as the defined soft delete. But a developer reading only the API reference ("permanently remove ... derived knowledge") would expect erasure, and the security page's "erasure limits" link points to a page that does not describe them (docs/api-facts.md section 6).

## Control: does deleting the namespace remove the preserved memories? (DEL-06)

Pre-registered as D12 (tag `prereg-del06`). Per run: seed one fact, delete the document, confirm the token left every normal surface, confirm `include.forgotten` still returns it, **delete the namespace**, re-create the same namespace with an unrelated document (a search on a deleted namespace cannot tell "erased" from "hidden"), then probe at 0, 5 and 30 seconds on every surface: search in all three modes with and without `include.forgotten`, the profile, the document list, a get on the old document ID.

Result: **PASS in 3 of 3 runs.** The preserved memory was returned before the namespace delete in every run, and the token was absent from every surface at every probe afterwards. So, as far as the API can show, namespace deletion does remove what a document delete preserves. The docs' suggested GDPR route (scope each end user to a namespace and delete the namespace) is consistent with that.

## Why it matters

A "delete my data" flow that deletes the user's documents leaves the extracted facts, which are often the personal data itself, stored and retrievable by anyone holding a key for that namespace who asks for forgotten entries. Other tenants cannot reach them (ISO-01 to ISO-05), and deleting the namespace removes them, so the exposure is narrow: but it is not what "permanently remove" suggests.

## Suggested fix (for the vendor to judge)

Say in one place, on the delete-documents reference, that deleting a document soft-deletes its derived memories (preserved, `isLatest: false`, returned by `include.forgotten`); state that namespace deletion is the way to remove them; document `include.forgotten` on the memory-operations page; use one spelling of the flag (`forgotten` works; the blog says `forgottenMemories`). Optionally offer a hard-delete option on document delete.

## Caveats

Free plan, one fact per run, one account. "Absent from the API" is all this can show; backups and internal stores are invisible to it. The memory-list probe with `include.forgotten` never returned the preserved memory even before the namespace delete, so it adds no evidence either way; the search probes are the informative ones. Server behavior can change.
