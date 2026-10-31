# Default-mode (`dreaming: "dynamic"`) COR-01 sample, 2026-10-30

Supplementary, **not part of any verdict** (docs/decisions.md D8). One run of COR-01 with `dreaming` left at its default.

Result: SKIPPED by the harness's own rule. In 3 of 3 attempts (fresh namespace and token each time, one short document per namespace):

- the document reached `status: done`, but `system.dreamingStatus` was still `dreaming` after the full 15-minute wait;
- no memory containing the token surfaced in memory search during a further ~15 minutes.

So roughly 30 minutes per attempt without a derived memory. The docs say memories "may form minutes after `status: done`" and a fresh namespace "can show zero memories ... for several minutes" (api-facts.md section 2). With `dreaming: "instant"`, the same facts surfaced about 1 second after `dreamingStatus: done` in 18 of 18 official COR runs.

Caveats: free plan, one account, one machine, one short document per namespace (the docs say dynamic mode "batches related docs", so a lone document may wait for a batch), and I never observed what happened after the wait ended because the namespaces were deleted. This is a characterization to follow up in LAT, not a bug claim.

## Addendum (LAT-04, same day)

The caveat above guessed that a lone document might be waiting for a batch. LAT-04 tested that: a namespace with three related documents also produced no memory and no `dreamingStatus: done` within 30 minutes, as did two lone-document namespaces. See `findings/F-002-dynamic-dreaming-no-memories.md`.

## Addendum 2 (2026-10-31): the memories did arrive

The LAT-04 namespaces survived the end of the session. Their server timestamps show dreaming completing about 4 hours 4 minutes after `add` for all five documents, in one 26-second window. Raw responses: `server-timestamps-lat04.json`. See `findings/F-002-dynamic-dreaming-no-memories.md`.
