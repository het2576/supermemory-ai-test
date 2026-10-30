"""Day-1 smoke cycle: add -> poll until searchable -> search -> delete -> confirm gone.

Output goes to smoke/ and is EXCLUDED from results (decisions.md D1); say what it showed in the report.
Usage: python -m scripts.smoke            (reads SUPERMEMORY_API_KEY from the environment or .env)
       python -m scripts.smoke --provider mock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.cycle import run_cycle
from src.env import load_dotenv
from src.recorder import scrub
from src.runner import make_provider


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="supermemory", choices=["supermemory", "mock"])
    args = ap.parse_args()

    if args.provider == "supermemory" and not os.environ.get("SUPERMEMORY_API_KEY"):
        print("SUPERMEMORY_API_KEY is not set (put it in .env or export it). Nothing was called.", file=sys.stderr)
        return 2

    provider, key = make_provider(args.provider)
    outcome = run_cycle(provider, log=print)
    print(f"\nRESULT: {outcome.result}  time_to_consistency_s={outcome.time_to_consistency_s}  {outcome.notes}")

    out = Path("smoke")
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"smoke-{args.provider}-{stamp}.json"
    payload = scrub({"outcome": outcome.__dict__, "exchanges": provider.drain_exchanges()}, [key])
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"raw exchanges saved to {path}")
    return 0 if outcome.result in ("PASS", "SLOW") else 1


if __name__ == "__main__":
    raise SystemExit(main())
