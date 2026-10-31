"""Turns the evidence files into the tables of REPORT.md, so no number in the report is typed by hand.

    python -m src.report                      # print every generated block
    python -m src.report --write REPORT.md    # replace the <!-- BEGIN:name --> ... <!-- END:name --> blocks in a file

Every row links to the run files it was computed from. Statistics follow docs/decisions.md D9 (LAT) and D10 (ABS):
nearest-rank percentiles on pooled samples, n always shown, p95 marked with * when it is just the maximum (n < 20)."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from .abstention import class_summary, reliably_removes_junk, separation
from .latency import fmt, summarize

DATE_GLOB = "runs/*"


def load(results: Path) -> dict[str, Any]:
    """Merge every day folder: {"summary": [...], "runs": {test_id: [payload per run, in run order]}, "files": {test_id: [paths]}}.
    A test that appears on more than one day (a rerun) is taken from the latest day only."""
    summary: dict[str, dict] = {}
    runs: dict[str, list[dict]] = {}
    files: dict[str, list[Path]] = {}
    for day in sorted(d for d in (results / "runs").iterdir() if (d / "results.json").exists()):
        for entry in json.loads((day / "results.json").read_text())["summary"]:
            tid = entry["testId"]
            summary[tid] = entry
            runs[tid], files[tid] = [], []
            found = sorted(day.glob(f"{tid}-run*.json"), key=lambda f: int(re.search(r"run(\d+)", f.name).group(1)))  # type: ignore[union-attr]
            for f in found:
                runs[tid].append(json.loads(f.read_text()))
                files[tid].append(f)
    return {"summary": list(summary.values()), "runs": runs, "files": files}


def _runs(per_run: list[str]) -> str:
    return f"{len(per_run)}/{len(per_run)} {per_run[0]}" if len(set(per_run)) == 1 else " ".join(per_run)


def _links(paths: list[Path], base: Path) -> str:
    return " ".join(f"[{i}]({os.path.relpath(p, base).replace(os.sep, '/')})" for i, p in enumerate(paths, 1))


def _names() -> dict[str, str]:
    from .runner import discover_tests

    return {t.id: t.title for t in discover_tests("tests")}


def _detail(tid: str, payloads: list[dict]) -> str:
    recs = [p["record"] for p in payloads]
    if tid.startswith("DEL"):
        ttc = [r["timeToConsistencySec"] for r in recs if r.get("timeToConsistencySec") is not None]
        return f"gone by {max(ttc):g}s in every run" if ttc and len(ttc) == len(recs) and max(ttc) == 0 else (f"time to gone, max {max(ttc):g}s" if ttc else (recs[0]["notes"][:90] or "-"))
    if tid.startswith("ISO"):
        probes = sum(1 for r in recs for c in r["checkpoints"] if "leaks" in c and "t" in c)
        leaks = sum(len(c["leaks"]) for r in recs for c in r["checkpoints"] if "leaks" in c and "t" in c)
        head = f"{leaks} foreign items in {probes} probes" if probes else ""
        note = recs[0]["notes"][:110] if recs[0]["notes"] else ""
        return "; ".join(x for x in (head, note) if x) or "-"
    if tid.startswith("COR"):
        conv = [p["extra"].get("converged_at_s") for p in payloads if isinstance(p.get("extra"), dict)]
        return ("correct from the first probe in every run" if conv and all(c == 0 for c in conv) else recs[0]["notes"][:90] or "-")
    if tid.split("-")[0] in ("LAT", "ABS", "POI"):
        return "numbers only, see the tables below"
    return recs[0]["notes"][:100] or "-"


def block_summary(data: dict, base: Path) -> str:
    names = _names()
    rows = ["| Test | What | Result | Runs | Detail | Evidence |", "|---|---|---|---|---|---|"]
    for s in sorted(data["summary"], key=lambda x: x["testId"]):
        tid = s["testId"]
        rows.append(
            f"| {tid} | {names.get(tid, '')} | **{s['final']}** | {_runs(s['perRun'])} | {_detail(tid, data['runs'][tid])} | {_links(data['files'][tid], base)} |"
        )
    return "\n".join(rows)


# --- LAT -------------------------------------------------------------------------------------


def _pool(data: dict, tid: str, getter) -> dict[str, Any]:
    vals = [v for p in data["runs"].get(tid, []) for v in getter(p["extra"])]
    return summarize(vals, total=len(vals))


def block_lat(data: dict, base: Path) -> str:
    def row(label, tid, getter, unit="s", digits=1):
        st = _pool(data, tid, getter)
        if not st["n"]:
            return f"| {label} | - | - | - | 0 |"
        star = "*" if st["p95_is_max"] else ""
        miss = f" (+{st['n_total'] - st['n']} not within cap)" if st["n"] < st["n_total"] else ""
        f = lambda v: f"{v:.{digits}f}{unit}"  # noqa: E731
        return f"| {label} | {f(st['p50'])} | {f(st['p95'])}{star} | {f(st['max'])} | {st['n']}{miss} |"

    ev = lambda tid: _links(data["files"].get(tid, []), base)  # noqa: E731
    out = ["Times are seconds from the moment `add` returns, from one machine (home network, India). Percentiles are nearest-rank on the pooled runs; `*` = p95 is the maximum because n < 20.", "",
           "| Measure | p50 | p95 | max | n |", "|---|---|---|---|---|"]
    out += [
        row("Ingest (default dreaming): first chunk-search hit", "LAT-01", lambda x: [s["chunk_hit"] for s in x["samples"]]),
        row("Ingest (default dreaming): `status: done`", "LAT-01", lambda x: [s["done"] for s in x["samples"]]),
        row("`add` call duration", "LAT-01", lambda x: [s["add_ms"] for s in x["samples"]], "ms", 0),
        row("Instant dreaming: `status: done`", "LAT-03", lambda x: [s["done"] for s in x["samples"]]),
        row("Instant dreaming: `dreamingStatus: done`", "LAT-03", lambda x: [s["dreaming_done"] for s in x["samples"]]),
        row("Instant dreaming: first memory-search hit", "LAT-03", lambda x: [s["memory_hit"] for s in x["samples"]]),
    ]
    for mode in ("chunks", "memories", "hybrid"):
        out.append(row(f"Search round trip, `{mode}`", "LAT-02", lambda x, m=mode: [r["ms"] for r in x["samples"][m] if r["http"] == 200], "ms", 0))
    cold = [round(p["extra"]["cold_ms"]) for p in data["runs"].get("LAT-02", [])]
    out += ["", f"Cold first search per run: {cold} ms. Evidence: LAT-01 {ev('LAT-01')}, LAT-02 {ev('LAT-02')}, LAT-03 {ev('LAT-03')}."]
    pairs = [(s["done"], s["chunk_hit"]) for p in data["runs"].get("LAT-01", []) for s in p["extra"]["samples"] if s["done"] is not None and s["chunk_hit"] is not None]
    if pairs:
        earlier = [d - h for d, h in pairs if h < d]
        out.append(f"\nChunk search returned the document before its status said `done` in {len(earlier)} of {len(pairs)} documents (median gap {sorted(earlier)[len(earlier) // 2]:.1f}s)." if earlier else "")
    rows = [r for p in data["runs"].get("LAT-04", []) for r in p["extra"]["rows"]]
    if rows:
        cap = data["runs"]["LAT-04"][0]["extra"]["cap_s"]
        show = lambda v: "not within cap" if v is None else f"{v:.0f}s"  # noqa: E731
        out += ["", f"Default (`dynamic`) dreaming, one run, cap {cap:.0f}s ({ev('LAT-04')}):", "", "| Document | `status: done` | `dreamingStatus: done` | First memory hit |", "|---|---|---|---|"]
        out += [f"| {r['doc']} | {show(r['done'])} | {show(r['dreaming_done'])} | {show(r['memory_hit'])} |" for r in rows]
    return "\n".join(x for x in out if x is not None)


# --- ABS -------------------------------------------------------------------------------------


def _rows(data: dict, tid: str) -> list[dict]:
    return [r for p in data["runs"].get(tid, []) for r in p["extra"]["rows"]]


def block_abs(data: dict, base: Path) -> str:
    a1, a2 = _rows(data, "ABS-01"), _rows(data, "ABS-02")
    if not a1 or not a2:
        return "_ABS has not been run._"

    def tops(rows, cls, mode, thr):
        return [r["top"] for r in rows if r["class"] == cls and r["mode"] == mode and r["threshold"] == thr]

    f = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    out = ["Top `similarity` per query at `threshold: 0` (nothing hidden by the server), pooled over 3 runs. AUC = probability that a random answerable query scores above a random unanswerable one; gap = lowest answerable top minus highest unanswerable top (positive means a threshold separates them perfectly).", "",
           "| Mode | Unanswerable class | n | Their top score (min / p50 / max) | Answerable top (min / p50 / max) | AUC | Gap | Separable |", "|---|---|---|---|---|---|---|---|"]
    for mode in ("chunks", "memories", "hybrid"):
        A = tops(a1, "answerable", mode, 0.0)
        cA = class_summary(A)
        for name, rows in (("near-miss", a1), ("off-domain", a2), ("nonsense", a2)):
            U = tops(rows, name.replace("-", "_"), mode, 0.0)
            c, s = class_summary(U), separation(A, U)
            out.append(f"| {mode} | {name} | {c['n']} | {f(c['min'])} / {f(c['p50'])} / {f(c['max'])} | {f(cA['min'])} / {f(cA['p50'])} / {f(cA['max'])} | {s['auc']:.3f} | {s['gap']:+.3f} | {'yes' if s['separable'] else 'no'} |")

    out += ["", "At the default threshold (parameter omitted, `hybrid`), unanswerable queries that still returned results, per run:", ""]
    for name, rows, total in (("near-miss", a1, 20), ("off-domain", a2, 10), ("nonsense", a2, 5)):
        cls = name.replace("-", "_")
        per = [sum(1 for r in run if r["class"] == cls and r["mode"] == "hybrid" and r["threshold"] is None and r["n"] > 0) for run in (p["extra"]["rows"] for p in data["runs"]["ABS-01" if name == "near-miss" else "ABS-02"])]
        out.append(f"- {name}: {per} of {total}")

    sweeps = [p["extra"]["summary"] for p in data["runs"].get("ABS-03", [])]
    if sweeps:
        base_kept = sum(s["sweep"]["0"]["answerable_correct"] for s in sweeps) / len(sweeps)
        out += ["", "Threshold sweep (`hybrid`, all 55 queries), per run. Reading rule (D10): a threshold reliably removes junk if no unanswerable query returns anything in any run while at least 90% of the threshold-0 share of answerable queries still get their correct fact.", "",
                "| Threshold | Answerable with correct fact | Unanswerable with any result (of 35) | Reliably removes junk |", "|---|---|---|---|"]
        for t in ("omitted", "0", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8"):
            per = [s["sweep"][t] for s in sweeps]
            out.append(f"| {t} | {' / '.join(f'{p['answerable_correct']:.0%}' for p in per)} | {' / '.join(str(p['unanswerable_any']) for p in per)} | {'yes' if reliably_removes_junk(per, base_kept) else 'no'} |")
        out += ["", f"`omitted` equals `0.3` in {sum(s['omitted_equals_0.3'] for s in sweeps)} of {len(sweeps)} runs. Queries whose server-side result was identical to filtering the threshold-0 results by `similarity >= t` (run 1): "
                + ", ".join(f"t={t}: {v}" for t, v in sweeps[0]["server_filter_equals_client_filter"].items()) + ".",
                "", f"Evidence: ABS-01 {_links(data['files']['ABS-01'], base)}, ABS-02 {_links(data['files']['ABS-02'], base)}, ABS-03 {_links(data['files']['ABS-03'], base)}."]
    return "\n".join(out)


# --- POI -------------------------------------------------------------------------------------


def block_poi(data: dict, base: Path) -> str:
    if "POI-01" not in data["runs"]:
        return "_POI has not been run._"
    out = ["For each planted document: how it came back on each surface, counted over the runs. `verbatim` = the planted wording survives, `rewritten` = the canary survives in other wording, `absent` = not returned. Role cues are the labels from the planted text that survived (e.g. `SYSTEM`, `assistant:`).", "",
           "| Planted text | Surface | Form (runs) | Role cues kept | Marked in text | Fields outside the documented set |", "|---|---|---|---|---|---|"]
    for tid in ("POI-01", "POI-02"):
        payloads = data["runs"].get(tid, [])
        names = list(payloads[0]["extra"]["reports"]) if payloads else []
        for name in names:
            surfaces = list(payloads[0]["extra"]["reports"][name])
            for s in surfaces:
                reps = [p["extra"]["reports"][name][s] for p in payloads]
                forms: dict[str, int] = {}
                for r in reps:
                    forms[r["form"]] = forms.get(r["form"], 0) + 1
                cues = sorted({c for r in reps for c in r["cues_kept"]})
                extra = sorted({k for r in reps for k in r.get("extra_fields", [])})
                out.append(f"| {tid} {name} | {s} | {', '.join(f'{k} {v}/{len(reps)}' for k, v in forms.items())} | {', '.join(cues) or '-'} | {sum(r['marked_in_text'] for r in reps)}/{len(reps)} | {', '.join(extra) or 'none'} |")
    out.append("\nEvidence: " + ", ".join(f"{t} {_links(data['files'][t], base)}" for t in ("POI-01", "POI-02") if t in data["files"]) + ".")
    return "\n".join(out)


# --- supplementary and superseded ---------------------------------------------------------------


def block_superseded(results: Path, base: Path) -> str:
    out = ["| Attempt | Why it is not the reported result |", "|---|---|"]
    for d in sorted((results / "superseded").glob("*")):
        readme = d / "README.md"
        why = " ".join(readme.read_text().split())[:260] if readme.exists() else "see directory"
        out.append(f"| [{d.name}]({os.path.relpath(d, base).replace(os.sep, '/')}/) | {why} |")
    return "\n".join(out)


BLOCKS = {"summary": block_summary, "lat": block_lat, "abs": block_abs, "poi": block_poi}


def build(results: Path, base: Path) -> dict[str, str]:
    data = load(results)
    out = {name: fn(data, base) for name, fn in BLOCKS.items()}
    out["superseded"] = block_superseded(results, base)
    return out


def write_into(path: Path, blocks: dict[str, str]) -> list[str]:
    text = path.read_text()
    done = []
    for name, body in blocks.items():
        pat = re.compile(rf"(<!-- BEGIN:{name} -->\n).*?(\n<!-- END:{name} -->)", re.S)
        if pat.search(text):
            text = pat.sub(lambda m: m.group(1) + body + m.group(2), text)
            done.append(name)
    path.write_text(text)
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--write", help="file with <!-- BEGIN:name --> / <!-- END:name --> markers to fill")
    args = ap.parse_args()
    results, base = Path(args.results), Path.cwd()
    blocks = build(results, base)
    if args.write:
        print("filled:", ", ".join(write_into(Path(args.write), blocks)))
    else:
        for name, body in blocks.items():
            print(f"\n## {name}\n\n{body}")


if __name__ == "__main__":
    main()
