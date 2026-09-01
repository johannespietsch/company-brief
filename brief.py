#!/usr/bin/env python3
"""Company brief generator.

  brief.py fetch  "Acme NV" --where "Rotterdam, NL" --html
  brief.py render briefs/acme-nv.json --pages 4

Output lands in briefs/ (gitignored) named after the company unless -o or a
path after --html says otherwise.

fetch and render are separate so you can re-render (or hand-edit) a brief
without paying for another research run. Every fetch is costed, logged to
evals/runs.jsonl, and recorded as a replayable cassette.

  python -m evals report            aggregate cost and quality signals
  python -m evals replay <file>     re-derive a brief from a cassette, free
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path

import render as renderer
from client import credentials_present, load_dotenv
from schema import guards

BRIEFS_DIR = Path(__file__).parent / "briefs"
MODELS = {"opus": "claude-opus-5", "sonnet": "claude-sonnet-5"}
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

DEFAULT_CONTEXT = (
    "The reader runs an AI consulting and solutions business and is assessing "
    "where AI work could concretely be sold into this company. Be specific about "
    "operational pain, data and systems landscape, technical hiring, and stated "
    "priorities, so the reader can reason about which offerings would actually fit."
)


def default_path(company: str, suffix: str) -> Path:
    """briefs/<company-slug><suffix>. Re-running a company overwrites it; the
    cassette in evals/ is what keeps the history."""
    ascii_name = (unicodedata.normalize("NFKD", company)
                  .encode("ascii", "ignore").decode())
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return BRIEFS_DIR / f"{slug or 'brief'}{suffix}"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr)


def report(data: dict, target_pages: int | None) -> dict:
    """Guards and page estimate. Warn-only: nothing is dropped or rewritten."""
    from evals import metrics

    m = metrics.measure(data, target_pages)
    for issue in m["guard_detail"]:
        warn(issue)
    if m["overclaiming"]:
        warn("unverified is empty -- the README treats that as an overclaiming signal")

    line = (f"  estimated length: {m['sheets']} A4 page(s) "
            f"({m['content_pages']:.2f} pages of content)")
    if target_pages:
        line += f", asked for {target_pages}"
        if m["sheets"] > target_pages:
            line += (f"\n  ! {m['sheets'] - target_pages} page(s) over; drop the least "
                     f"important block by hand, or re-run with --pages {m['sheets']}")
    print(line, file=sys.stderr)
    return m


def confirm_spend(model: str, effort: str, assume_yes: bool, cache: bool = True) -> bool:
    from evals.estimate import render_estimate

    print(render_estimate(model, effort, cache), file=sys.stderr)
    if assume_yes:
        print("  --yes given, proceeding", file=sys.stderr)
        return True
    if not sys.stdin.isatty():
        print("  refusing to spend without confirmation; pass --yes", file=sys.stderr)
        return False
    try:
        return input("  proceed? [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False


def cmd_fetch(args: argparse.Namespace) -> int:
    load_dotenv()
    import prompts
    import research
    from evals import cassette, runlog
    from evals.pricing import cost, fmt

    model = MODELS.get(args.model, args.model)
    if not credentials_present():
        print("error: no ANTHROPIC_API_KEY in the environment or .env", file=sys.stderr)
        return 1
    if not confirm_spend(model, args.effort, args.yes, not args.no_cache):
        print("aborted, nothing spent", file=sys.stderr)
        return 1

    user = prompts.user_prompt(
        company_name=args.company,
        country_city_or_url=args.where or "",
        stance=args.stance,
        page_count=str(args.pages),
        why_the_reader_cares=args.context or "",
        focus=args.focus or "",
        offer=prompts.offer_from_profile(args.profile) if args.profile else "",
    )
    request_meta = {
        "company": args.company, "stance": args.stance, "pages": args.pages,
        "model": model, "effort": args.effort, "where": args.where, "focus": args.focus,
        "profile": str(args.profile) if args.profile else None,
        "cache": not args.no_cache,
    }
    print(f"researching {args.company} ({model}, effort={args.effort})...", file=sys.stderr)

    # The meter is built here, not inside research.run, so that a run which dies
    # part-way can still be costed -- an exception is not a return, so anything
    # constructed in there would be unreachable from the except branch.
    state = research.Run(model, args.effort)
    try:
        data, _ = research.run(
            prompts.system_prompt(), user,
            model=model, effort=args.effort, retry=not args.no_retry,
            progress=None if args.quiet else lambda line: print(f"  {line}", file=sys.stderr),
            cache=not args.no_cache, state=state,
        )
    except Exception as e:                        # noqa: BLE001 - logged, then re-raised as exit
        # cost() cannot raise UnknownModel here: confirm_spend already priced
        # this model above, so an unknown one never reaches the try.
        row = {**request_meta, "ok": False, "error": f"{type(e).__name__}: {e}",
               "usage": state.usage.as_dict(), "cost": cost(state.usage, model)}

        # The whole point of this branch is to preserve the record of a run
        # that failed, so writing the tape is best-effort: a tape that will not
        # write must not take the log row with it, nor mask the real error.
        tape = None
        if state.responses:
            try:
                tape = cassette.save(
                    cassette.path_for(args.company, model, args.effort, partial=True),
                    request=request_meta, responses=state.responses, partial=True,
                )
                try:
                    row["cassette"] = str(tape.relative_to(Path(__file__).parent))
                except ValueError:                # a tape written outside the project
                    row["cassette"] = str(tape)
            except Exception as tape_error:        # noqa: BLE001 - never mask `e`
                row["cassette_error"] = f"{type(tape_error).__name__}: {tape_error}"

        runlog.append(row)
        print(f"error: {e}", file=sys.stderr)
        if state.usage.requests:
            print(f"  spent anyway: {fmt(row['cost']['total'])} over "
                  f"{state.usage.requests} request(s)", file=sys.stderr)
        if tape is not None:
            print(f"  partial cassette {tape.name}", file=sys.stderr)
        elif "cassette_error" in row:
            warn(f"could not write the partial cassette: {row['cassette_error']}")
        return 1

    out = args.out or default_path(args.company, ".json")
    write(out, json.dumps(data, indent=2, ensure_ascii=False))

    tape = cassette.save(
        cassette.path_for(args.company, model, args.effort),
        request=request_meta, responses=state.responses,
    )
    spend = cost(state.usage, model)
    u = state.usage
    print(f"  {fmt(spend['total'])}  {u.input_tokens}in/{u.output_tokens}out  "
          f"{u.web_searches} searches, {u.web_fetches} fetches  "
          f"{u.requests} request(s), {state.attempts} attempt(s), {u.seconds:.0f}s",
          file=sys.stderr)

    m = report(data, args.pages)
    runlog.append({**request_meta, "ok": True, "attempts": state.attempts,
                   "usage": u.as_dict(), "cost": spend, "metrics": m,
                   "cassette": str(tape.relative_to(Path(__file__).parent))})
    print(f"  cassette {tape.name}", file=sys.stderr)

    # --html with no path renders beside the JSON.
    if args.html is not None:
        html = Path(args.html) if args.html else out.with_suffix(".html")
        write(html, renderer.render(data))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    data = json.loads(args.brief.read_text(encoding="utf-8"))
    write(args.out or args.brief.with_suffix(".html"), renderer.render(data))
    report(data, args.pages)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="research a company and write brief JSON")
    f.add_argument("company")
    # DEMAND by default: its "implications for an external provider" section is
    # the one that feeds a decision about what to offer them. DUAL when they
    # might also be a partner or competitor.
    f.add_argument("--stance", choices=["SUPPLIER", "DEMAND", "DUAL"], default="DEMAND")
    f.add_argument("--where", help="city, country or URL, to avoid same-name collisions")
    f.add_argument("--context", default=DEFAULT_CONTEXT,
                   help="why the reader cares (defaults to the AI-consulting framing)")
    f.add_argument("--focus", help="optional specific focus")
    f.add_argument("--profile", type=Path,
                   help="outreach-profile.md; its offering sections steer openings "
                        "and contacts (omit for a neutral brief)")
    f.add_argument("--pages", type=int, default=4, choices=range(2, 6))
    f.add_argument("--model", default="opus", help="opus | sonnet | a full model id")
    # temperature is rejected on Opus 5 / Sonnet 5; effort is the lever instead.
    f.add_argument("--effort", default="high", choices=EFFORTS)
    f.add_argument("--no-retry", action="store_true",
                   help="do not retry when unverified comes back empty")
    f.add_argument("-y", "--yes", action="store_true", help="skip the cost confirmation")
    f.add_argument("-q", "--quiet", action="store_true",
                   help="no per-search progress lines while researching")
    # Caching cut a measured brief by 75%% with no change to the research done;
    # the flag exists to reproduce tools/ab_caching.py, not for normal use.
    f.add_argument("--no-cache", action="store_true",
                   help="disable prompt caching (roughly 4x more expensive)")
    f.add_argument("-o", "--out", type=Path,
                   help="JSON path (default briefs/<company>.json)")
    f.add_argument("--html", nargs="?", const="", metavar="PATH",
                   help="also render straight away, beside the JSON unless "
                        "given a path")
    f.set_defaults(func=cmd_fetch)

    r = sub.add_parser("render", help="turn brief JSON into HTML")
    r.add_argument("brief", type=Path)
    r.add_argument("-o", "--out", type=Path)
    r.add_argument("--pages", type=int, help="target page count, for the overflow warning")
    r.set_defaults(func=cmd_render)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
