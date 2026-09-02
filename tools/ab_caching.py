#!/usr/bin/env python3
"""Measure what prompt caching actually saves on a research turn.

Runs the same reduced-budget brief twice -- caching off, then on -- and compares
billed input against cache reads. Reduced `max_uses` keeps the test near $1
instead of the ~$13 two full briefs would cost; the amplification effect being
measured is the same shape, just smaller.

Order matters: the no-cache arm runs first so it cannot warm the cache for the
arm that follows.

    .venv/bin/python tools/ab_caching.py "Vondel Logistiek"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prompts                                  # noqa: E402
import research                                 # noqa: E402
from client import make_client                  # noqa: E402
from evals.pricing import cost, fmt             # noqa: E402

MODEL = "claude-opus-5"
EFFORT = "high"


def arm(label: str, company: str, cache: bool) -> dict:
    state = research.Run(MODEL, EFFORT)
    user = prompts.user_prompt(
        company_name=company, country_city_or_url="", stance="DEMAND",
        page_count="3",
        why_the_reader_cares="Assessing where AI consulting work could be sold in.",
        focus="")
    print(f"\n--- {label} (cache={cache}) ---")
    research._collect(
        make_client(), state, system=prompts.system_prompt(),
        messages=[{"role": "user", "content": user}],
        progress=lambda l: print(f"  {l}", flush=True), cache=cache)
    u = state.usage
    c = cost(u, MODEL)
    print(f"  input {u.input_tokens:,}  cache_read {u.cache_read_tokens:,}  "
          f"cache_write {u.cache_write_5m_tokens + u.cache_write_1h_tokens:,}")
    print(f"  searches {u.web_searches} fetches {u.web_fetches}  "
          f"{u.seconds:.0f}s  {fmt(c['total'])}")
    return {"usage": u, "cost": c}


def main() -> int:
    company = sys.argv[1] if len(sys.argv) > 1 else "Vondel Logistiek"
    # Reduced budget so the experiment is affordable.
    research.TOOLS = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 6},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 4},
    ]
    research.MAX_TOKENS = 16000

    off = arm("A  caching OFF", company, cache=False)
    on = arm("B  caching ON", company, cache=True)

    a, b = off["cost"]["total"], on["cost"]["total"]
    ua, ub = off["usage"], on["usage"]
    print("\n" + "=" * 62)
    print(f"{'':22} {'A off':>13} {'B on':>13}")
    for label, key in [("billed input tok", "input_tokens"),
                       ("cache read tok", "cache_read_tokens"),
                       ("cache write tok", "cache_write_5m_tokens"),
                       ("searches", "web_searches"),
                       ("fetches", "web_fetches")]:
        print(f"  {label:20} {getattr(ua, key):>13,} {getattr(ub, key):>13,}")
    print(f"  {'cost':20} {fmt(a):>13} {fmt(b):>13}")
    if a:
        print(f"\n  delta: {(b - a) / a * 100:+.1f}%   "
              f"({'cheaper' if b < a else 'NOT cheaper'} with caching)")
    tot_b = ub.input_tokens + ub.cache_read_tokens
    if tot_b:
        print(f"  cache hit rate in B: {ub.cache_read_tokens / tot_b * 100:.1f}% of input tokens")
    print(f"  experiment cost: {fmt(a + b)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
