"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    base_rows = base.get("rows") or []

    # 1. Metric values must be finite numbers (NaN < min is False: a naive gate lets it through).
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (not a finite number)")

    # 2. Graders must have run on every row.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the PR run")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    missing = sum(1 for r in rows for m in graded if m in r and r[m] is None)
    absent = sorted({m for r in rows for m in graded if m not in r and any(m in b for b in base_rows)})
    if missing:
        problems.append(f"{missing} row value(s) are None for graded metrics (crashed grader dropped from the mean)")
    if absent:
        problems.append(f"PR rows lack graded metric(s) the baseline has: {absent}")

    # 3. Row count and the exact (item, seed) grid.
    man = pr.get("manifest") or {}
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = len(keys) - len(set(keys))
    if dups:
        problems.append(f"{dups} duplicated (item, seed) row(s)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        problems.append(f"(item, seed) set differs from the baseline: {len(set(keys) - base_keys)} extra, "
                        f"{len(base_keys - set(keys))} missing (dropped rows or cherry-picked seeds)")
    if int(man.get("items") or 0) != int((base.get("manifest") or {}).get("items") or 0):
        problems.append("manifest item count differs from the baseline's")

    # 4. Reported metrics must be what the rows say (a hand-edited headline number).
    if rows and not problems:
        ids = [m for m in graded if all(m in r for r in rows)]
        has_cost = all("cost" in r for r in rows)
        again = aggregate(rows if has_cost else [{**r, "cost": 0.0} for r in rows], ids,
                          k_values=spec.get("pass_k", []))
        if not has_cost:
            again.pop("cost_per_success", None)
        for k, v in again.items():
            got = (pr.get("metrics") or {}).get(k)
            if isinstance(v, (int, float)) and isinstance(got, (int, float)) and abs(float(v) - float(got)) > 1e-6:
                problems.append(f"metric {k}={got} does not match its rows ({v})")

    # 5. Slice tags are fixed by the eval set; relabelling an item hides its regression.
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    relabelled = sorted({r.get("item_id") for r in rows
                         if r.get("item_id") in base_slices and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]})
    if relabelled:
        problems.append(f"slice tags differ from the baseline on {relabelled[:5]}")

    # 6. Ratchet: same eval-set version => thresholds may only get stricter.
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return problems


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    out: list[str] = []
    new = {m["id"]: m for m in spec.get("metrics", [])}
    for old in base_spec.get("metrics", []):
        mid = old["id"]
        if mid not in new:
            out.append(f"ratchet: metric {mid} removed")
            continue
        out += [f"ratchet: {mid} {p}" for p in _looser(old, new[mid], old.get("threshold") or {}, new[mid].get("threshold") or {})]
    new_sl = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        key = (old.get("name"), old.get("metric"))
        if key not in new_sl:
            out.append(f"ratchet: slice {key[0]}/{key[1]} removed")
            continue
        out += [f"ratchet: slice {key[0]}/{key[1]} {p}" for p in _looser(old, new_sl[key], old, new_sl[key])]
    return out


def _looser(old: dict, new: dict, th_old: dict, th_new: dict) -> list[str]:
    out = []
    if old.get("blocking") and not new.get("blocking"):
        out.append("is no longer blocking")
    if th_old.get("no_significant_drop") and not th_new.get("no_significant_drop"):
        out.append("dropped no_significant_drop")
    for key in ("min",):
        if key in th_old and (key not in th_new or th_new[key] < th_old[key]):
            out.append(f"min lowered {th_old[key]} -> {th_new.get(key)}")
    for key in ("max", "max_increase"):
        if key in th_old and (key not in th_new or th_new[key] > th_old[key]):
            out.append(f"{key} raised {th_old[key]} -> {th_new.get(key)}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        if not a:
            verdict, val, note = "missing", None, "no rows in slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            verdict, note = "ok", ""
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<40} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
