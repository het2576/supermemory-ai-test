# Critic report for Supermemory

You asked for critics. I wrote a small open test suite for what benchmarks skip (deletion, tenant isolation, corrections, abstention, stored text, latency) and ran it against the v5 API on a free account on 2026-10-30/31. Numbers, caveats and raw evidence: [REPORT.md](REPORT.md). Nothing below is a security defect, and I found nothing that needs private disclosure.

## What already works

- **Deletes are immediate.** After a document delete, the content was gone from chunk, memory and hybrid search at the first probe in 12 of 12 runs, and a delete during processing was refused exactly as the docs say.
- **Tenants did not cross.** 0 foreign items in 33 probes, including near-duplicate content and look-alike IDs that differ by case or punctuation. Invalid IDs were rejected, not rewritten.
- **The newest fact wins.** 18 of 18 runs across explicit moves, implicit updates, a chain of three, and "used to X, now Y". Even a plain-text "forget what I said" retracted the fact, which the docs do not promise.
- **The docs matched the behavior** wherever I could check them: the delete-while-processing error, the namespace rules, the 0.3 default, `isLatest`, and a `threshold` that filters exactly as described.

## What I would fix, in order

1. **Default memory processing took about four hours, not "several minutes"** ([F-002](findings/F-002-dynamic-dreaming-no-memories.md)). With `dreaming: "dynamic"`, five documents in three namespaces had no memory at 30 minutes; the server's timestamps show all of them finishing 4 h 04 m after `add`. With `instant` it is about 26 seconds. This is already reported in claude-supermemory #156. Say the real expectation in the docs, or lead the quickstart with `instant`.
2. **"Delete" means four things on four pages** ([F-001](findings/F-001-deleted-documents-memories-preserved.md)). Deleting a document leaves its memories as soft-deleted records that `include.forgotten` still returns; the API reference says "permanently remove ... derived knowledge". Deleting the namespace does remove them (I tested it), and the security page says to do that, but the document-delete page should say so too. The blog spells the flag `forgottenMemories`; the API accepts `forgotten`.
3. **The default threshold never abstains** ([F-003](findings/F-003-default-threshold-never-abstains.md)). At 0.3 all 35 unanswerable queries, nonsense included, still returned results. Scores for answerable and near-miss questions touch (0.65 to 0.76 versus 0.54 to 0.655). A short "choosing a threshold" page with a score distribution, and a top-versus-next-score margin test, would help more than the number.
4. **Memory text is a paraphrase, and it can lose the speaker.** I stored an instruction written as a message from another user. The memory came back as "alice instructed the assistant to...", as "Assistant was instructed to...", and once as the bare fact "All users' password has been set to ...". A promise ("I will reveal") became an event ("was revealed"). Nothing in the response marks stored text as untrusted. A source or role field on memories, and a "treat as untrusted" note, would let developers do the right thing.
5. **No vulnerability-disclosure policy** on the security page: only a general support address for reports, DPAs and BAAs.

## A positioning draft

Your current line is "the best memory for agents: the kind people feel, not just the kind that tops a benchmark." The tests above are that kind of claim, so say it as something checkable:

> Memory you can verify. A delete shows up on the next search, one tenant never sees another, and the newest fact wins, with a public test suite to check each. Where it takes longer (default memory processing can take hours), we say so.

I would not claim "erased" for document deletes until the wording in point 2 is fixed.

## When to use it, and when to verify

- **Use it for** per-user memory where you scope each user to a namespace, read memories after `dreaming: "instant"`, and delete by namespace for erasure requests.
- **Verify first:** how long memories take on the default mode for your plan; what threshold works on your data (the default will not abstain); that your prompt delimits retrieved text as untrusted.
- **Not tested:** other plans, long documents and files, connectors, concurrency, and any quality benchmark.

Run it yourself: `pytest` then `python -m src.runner` with your own key ([README.md](README.md)).
