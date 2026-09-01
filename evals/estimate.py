"""Project the cost of a run before spending anything.

Uses the median of past runs at the same model/effort once there are three of
them; until then it uses a stated prior, which is a guess and is labelled as one.
"""

from __future__ import annotations

from evals import runlog
from evals.pricing import Usage, cost, fmt

# First-run prior, caching ON (the default).
#
# Measured full DEMAND brief at opus-5/effort=high without caching (a mid-size
# company, 2026-09-01): 31 tool calls, 1.14M billed input tokens, $6.43.
# tools/ab_caching.py then measured caching at the same shape on 2026-09-02:
# billed input collapsed from 516,622 to 28 tokens with a 100% hit rate, 75%
# cheaper overall. Applying that structure (97.3% read / 2.7% write) to the full
# run's token volume gives the numbers below, ~$1.45 rather than ~$6.43.
#
# Two earlier priors were wrong in opposite directions -- a hand-guessed 120k
# input (9.5x low), then 1.15M input (right for uncached, 4x high once caching
# was on). Once three runs exist at a config, runlog.prior() replaces this.
PRIORS = {
    # Caching on (the default): the same token volume, but read at 0.1x.
    True: {
        "input_tokens": 2_000,
        "cache_read_tokens": 1_114_000,
        "cache_write_5m_tokens": 31_000,
        "output_tokens": 22_000,
        "web_searches": 16,
        "web_fetches": 15,
    },
    # Caching off: the uncached run exactly as measured.
    False: {
        "input_tokens": 1_144_682,
        "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0,
        "output_tokens": 21_791,
        "web_searches": 16,
        "web_fetches": 15,
    },
}


def project(model: str, effort: str, cache: bool = True) -> tuple[dict, str]:
    """Returns (itemised cost, provenance note)."""
    measured = runlog.prior(model, effort, cache)
    if measured:
        source = (f"median of {measured['n']} past {model} runs at "
                  f"effort={effort}, cache={'on' if cache else 'off'}")
        basis = measured
    else:
        source = "prior (no measured runs at this config yet -- treat as rough)"
        basis = PRIORS[bool(cache)]
    usage = Usage(
        input_tokens=basis["input_tokens"],
        output_tokens=basis["output_tokens"],
        cache_read_tokens=basis.get("cache_read_tokens", 0),
        cache_write_5m_tokens=basis.get("cache_write_5m_tokens", 0),
        web_searches=basis["web_searches"],
        web_fetches=basis.get("web_fetches", 0),
    )
    return cost(usage, model), source


def render_estimate(model: str, effort: str, cache: bool = True) -> str:
    items, source = project(model, effort, cache)
    lines = [f"  projected cost: {fmt(items['total'])}   [{source}]"]
    for key in ("input", "cache_read", "cache_write", "output", "web_search"):
        if items[key]:
            lines.append(f"    {key:11} {fmt(items[key])}")
    return "\n".join(lines)
