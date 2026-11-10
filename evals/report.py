"""Aggregate the run log."""

from __future__ import annotations

import statistics
from collections import defaultdict

from evals import runlog
from evals.pricing import fmt


def _agg(rows: list[dict], key) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def _median(rows, path, default=0):
    vals = []
    for r in rows:
        cur = r
        for part in path.split("."):
            cur = (cur or {}).get(part) if isinstance(cur, dict) else None
        if isinstance(cur, (int, float)):
            vals.append(cur)
    return statistics.median(vals) if vals else default


def report(rows: list[dict] | None = None) -> str:
    rows = runlog.read() if rows is None else rows
    if not rows:
        return ("No runs logged yet. Run `brief.py fetch ...` and the log fills up at "
                f"{runlog.LOG_PATH}.")

    ok = [r for r in rows if r.get("ok")]
    spend = sum(r.get("cost", {}).get("total", 0) for r in rows)
    lines = [
        f"{len(rows)} run(s), {len(ok)} successful.  Total spend {fmt(spend)}"
        " (CLI runs at list-price equivalent, not billed).",
        "",
        "By config",
        f"  {'MODEL':17} {'EFFORT':7} {'VIA':4} {'CACHE':5} {'N':>3} {'$/BRIEF':>9} {'SEARCH':>7} "
        f"{'TOK_IN':>8} {'TOK_OUT':>8} {'REQS':>5} {'SECS':>6} {'WARN':>5} {'SHEETS':>7}",
    ]
    # Rows from before the CLI backend existed have no key: they were API runs.
    groups = _agg(ok, lambda r: (r.get("model", "?"), r.get("effort", "?"),
                                 r.get("backend", "api"),
                                 "on" if r.get("cache", False) else "off"))
    for (model, effort, via, cache), g in sorted(groups.items()):
        lines.append(
            f"  {model:17} {effort:7} {via:4} {cache:5} {len(g):>3} "
            f"{_median(g, 'cost.total'):>9.4f} "
            f"{_median(g, 'usage.web_searches'):>7.0f} "
            f"{_median(g, 'usage.input_tokens'):>8.0f} "
            f"{_median(g, 'usage.output_tokens'):>8.0f} "
            f"{_median(g, 'usage.requests'):>5.0f} "
            f"{_median(g, 'usage.seconds'):>6.0f} "
            f"{_median(g, 'metrics.guard_warnings'):>5.0f} "
            f"{_median(g, 'metrics.sheets'):>7.0f}"
        )

    failed = [r for r in rows if not r.get("ok")]
    if failed:
        lines += ["", f"Failures ({len(failed)})"]
        for r in failed[-5:]:
            lines.append(f"  {r.get('ts', '?')}  {r.get('company', '?')}  {r.get('error', '?')[:70]}")

    over = [r for r in ok if (r.get("metrics") or {}).get("pages_delta", 0) > 0]
    oc = [r for r in ok if (r.get("metrics") or {}).get("overclaiming")]
    retried = [r for r in ok if r.get("attempts", 1) > 1]
    lines += [
        "",
        "Signals",
        f"  over requested length : {len(over)}/{len(ok)}",
        f"  empty unverified after retry : {len(oc)}/{len(ok)}",
        f"  needed the retry : {len(retried)}/{len(ok)}",
    ]

    lines += ["", "Recent runs",
              f"  {'WHEN':20} {'COMPANY':26} {'MODEL':16} {'EFF':7} {'$':>8} {'SH':>3} {'W':>3}"]
    for r in rows[-10:]:
        m = r.get("metrics") or {}
        lines.append(
            f"  {r.get('ts', '?')[:19]:20} {str(r.get('company', '?'))[:26]:26} "
            f"{str(r.get('model', '?'))[:16]:16} {str(r.get('effort', '?')):7} "
            f"{r.get('cost', {}).get('total', 0):>8.4f} "
            f"{m.get('sheets', 0):>3} {m.get('guard_warnings', 0):>3}"
        )
    return "\n".join(lines)
