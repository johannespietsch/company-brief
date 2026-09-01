"""python -m evals <report|replay|prices>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals import cassette, metrics, report
from evals.pricing import MODEL_PRICES, PRICES_FETCHED, WEB_SEARCH_PER_CALL


def cmd_report(args) -> int:
    print(report.report())
    return 0


def _report_partial(path: str, data: dict) -> int:
    """A partial tape is evidence from a run that never produced a brief.

    There is no brief JSON on it to re-derive, so rather than failing in the
    JSON parser with a confusing message, say what the tape actually holds --
    which is the point of keeping one.
    """
    req = data.get("request", {})
    responses = data.get("responses", [])
    kinds: dict[str, int] = {}
    for resp in responses:
        for block in resp.get("content", []):
            kind = block.get("type", "?")
            kinds[kind] = kinds.get(kind, 0) + 1

    print(f"partial tape {Path(path).name}")
    print(f"  recorded {data.get('recorded')}  {req.get('model')} "
          f"effort={req.get('effort')}  company={req.get('company')!r}")
    print(f"  {len(responses)} response(s), {sum(kinds.values())} block(s)")
    for kind, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {kind:34} {n}")
    print(f"  {len(cassette.replay_text(data)):,} char(s) of assistant text")
    sys.stdout.flush()                  # keep the note below the summary when piped
    print("  no brief to re-derive -- this tape records what the run had "
          "gathered when it died", file=sys.stderr)
    return 1


def cmd_replay(args) -> int:
    """Re-derive a brief and its metrics from a recorded run. Costs nothing."""
    data = cassette.load(args.cassette)
    if data.get("partial"):
        return _report_partial(args.cassette, data)
    text = cassette.replay_text(data)
    try:
        brief = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"recorded response is not valid JSON: {e}", file=sys.stderr)
        return 1
    req = data.get("request", {})
    print(f"replaying {Path(args.cassette).name}")
    print(f"  recorded {data.get('recorded')}  {req.get('model')} effort={req.get('effort')}")
    m = metrics.measure(brief, req.get("pages"))
    for k, v in m.items():
        if k == "guard_detail":
            for w in v:
                print(f"    ! {w}")
        else:
            print(f"  {k:16} {v}")
    if args.out:
        Path(args.out).write_text(json.dumps(brief, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0


def cmd_prices(args) -> int:
    print(f"USD per million tokens; fetched {PRICES_FETCHED}")
    print(f"  {'MODEL':20} {'IN':>8} {'OUT':>8} {'W5M':>8} {'W1H':>8} {'READ':>8}")
    for name, p in MODEL_PRICES.items():
        print(f"  {name:20} {p.input:>8.2f} {p.output:>8.2f} {p.cache_write_5m:>8.2f} "
              f"{p.cache_write_1h:>8.2f} {p.cache_read:>8.2f}")
    print(f"\n  web search  ${WEB_SEARCH_PER_CALL * 1000:.2f} per 1,000 searches")
    print("  web fetch   no additional charge")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m evals")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report", help="aggregate the run log").set_defaults(func=cmd_report)
    r = sub.add_parser("replay", help="re-derive metrics from a cassette, free")
    r.add_argument("cassette")
    r.add_argument("-o", "--out", help="also write the brief JSON here")
    r.set_defaults(func=cmd_replay)
    sub.add_parser("prices", help="show the price table").set_defaults(func=cmd_prices)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
