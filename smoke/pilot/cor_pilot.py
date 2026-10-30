"""COR pilot against the real API. Excluded from results. Prints texts and flags only (no headers, no key)."""
import json, sys, time
from src.runner import make_provider
from src.clock import RealClock
from src.adapter import AddOptions, SearchOptions
from src.assertions import scope_id, canary
from src.deletion import wait_done, wait_found

from src.env import load_dotenv; load_dotenv()
p, _key = make_provider("supermemory"); clock = RealClock()
scope = scope_id("memtrust_corpilot")
t1, t2 = canary("COR"), canary("COR")
print("scope", scope, t1, t2)
def add(text):
    r = p.add(scope, text, AddOptions(dreaming="instant"))
    s = wait_done(p, scope, r.doc_id, clock, timeout_s=300, dreaming=True)
    print("added", r.doc_id, "status", s.value.status if s.value else None, s.value.dreaming_status if s.value else None, round(s.elapsed_s,1))
    return r.doc_id
q = "Which city does Ravi live in?"
add(f"Ravi lives in the city of Zorvania-{t1}.")
time.sleep(3)
add(f"Ravi moved. Ravi now lives in the city of Quentaria-{t2}.")
for i in range(6):
    for mode in ("memories", "hybrid"):
        for fg in (False, True):
            r = p.search(scope, q, SearchOptions(mode=mode, include_forgotten=fg, include_related=True))
            print(f"-- try{i} mode={mode} forgotten={fg} http={r.http_status} n={len(r.hits)}")
            for h in r.hits:
                print("   ", h.kind, "latest=",h.is_latest, "inf=",h.is_inference, "score=",h.score, repr(h.text[:140]))
    if i == 0:
        print("RAW (memories) first result keys:")
        r = p.search(scope, q, SearchOptions(mode="memories", include_related=True))
        if r.hits: print(json.dumps(r.hits[0].raw, default=str)[:900])
    time.sleep(10)
print("profile:", p.profile(scope).entries)
p.delete_scope(scope)
