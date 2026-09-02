# Company Brief Generator

A prompt pack plus a small script around it. The model researches a company with
web search and returns strict JSON; the script validates it and renders A4-print HTML.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env && $EDITOR .env          # key, and workspace id if needed

.venv/bin/python brief.py fetch "Vondel Logistiek" --where "Rotterdam, NL" --html
.venv/bin/python brief.py render briefs/vondel-logistiek.json --pages 4  # free re-render
.venv/bin/python -m evals report                          # what it all cost
```

`fetch` prints a projected cost and waits for confirmation before spending
(`--yes` to skip). Requires `anthropic>=1.0`; a project-local `.venv` keeps that
off any other project sharing your interpreter.

Both land in `briefs/` (gitignored), named after the company; `-o` and a path
after `--html` override that. Re-running a company overwrites its files —
the cassettes under `evals/` are what keep the history.

`fetch` and `render` are separate so you can re-render, or hand-edit the JSON,
without paying for another research run. Print to PDF from the browser.

| File | |
|---|---|
| `brief.py` | CLI: `fetch` and `render` |
| `research.py` | the API call — tools, schema, `pause_turn` handling |
| `prompts.py` | loads `prompts/`, fills the `{{...}}` template |
| `schema.py` | the JSON schema the API enforces, plus the guards below |
| `render.py` | HTML, and the page-length estimate |
| `client.py` | client construction, `.env` loading, workspace header |
| `evals/` | cost model, run log, cassettes, deterministic metrics |
| `tools/measure.py` | recalibrates the page estimate if you change the CSS |
| `tools/check_citations.py` | checks structured outputs still works with the web tools |

Useful flags: `--stance SUPPLIER|DEMAND|DUAL` (default `DEMAND`), `--pages 2-5`
(default 4), `--effort low..max` (default `high`), `--model opus|sonnet`,
`--focus`, `--context`, `--no-retry`.

---

## Call config

| Setting | Value | Why |
|---|---|---|
| Model | `claude-opus-5` for depth, `claude-sonnet-5` for volume | Opus holds contradictions across many sources better |
| `max_tokens` | 64000, streamed | The JSON payload is long, and streaming keeps a 20-search turn under the HTTP timeout |
| `output_config.effort` | `high` | Replaces `temperature`. Sampling parameters are rejected on both models above; effort is the lever that remains. `max` for a company with a messy corporate history |
| Tools | `web_search_20260209` + `web_fetch_20260209` | Snippets alone are not enough — see the fetch rule. `web_fetch` makes it enforceable |
| Output | `output_config.format` with the schema in `schema.py` | The API guarantees parseable, schema-conforming JSON, so there is no parse-error retry path |
| Retries | One, only when `unverified` comes back empty | See below |

The stance defaults to `DEMAND` because its closing "implications for an external
provider" section is the one that feeds a decision about what to offer them. Use
`DUAL` when the company might also be a partner or a competitor.

---

## Measuring what it costs

Every `fetch` appends a row to `evals/runs.jsonl` and saves the raw API responses
to `evals/cassettes/`. Nothing is sampled or aggregated away — the log is the
record of what actually happened.

```bash
python -m evals report            # spend, tokens, searches, latency by config
python -m evals replay <cassette> # re-derive a brief and its metrics, free
python -m evals prices            # the price table, and when it was fetched
```

Prices are in `evals/pricing.py`, from the pricing page on the date recorded
there. The two that matter here: **web search is $10 per 1,000 searches**, and
**web fetch is free** beyond the tokens the fetched page adds to context.
A research turn makes several *billed* requests — every `pause_turn` resume and
the overclaiming retry are separate calls — so usage is summed across all of
them rather than read off the final response.

Alongside cost, each run records deterministic signals: guard warnings, sheets
vs. requested pages, `unverified` length, block mix, word count. These do not
tell you a brief is *good*; they tell you it is well-formed, the right length,
and not obviously overclaiming — which is what you want to notice regressing
when you edit the prompt pack.

The cost projection shown before each run uses the median of your last runs at
that model and effort, once there are three of them. Before that it uses a
stated prior and says so.

---

## Notes from practice

**The identity check is not optional.** Two of three briefs in the run that produced this
template turned up a renamed or acquired entity that the requester's own framing had
missed. Putting it first in the research order changes the whole document.

**Company blogs are underrated as a demand signal.** For the DEMAND stance, a vendor's own
"trends we're watching" post is effectively a published roadmap. It gives you their stated
priorities in their own words, which is far stronger evidence than your inference about
what they probably need.

**Force the `unverified` array to be non-empty.** If the model returns an empty list on a
real company, it is almost certainly overclaiming somewhere. This is the one condition the
script retries on, and the schema deliberately does *not* require a minimum length —
forcing the field would buy a fabricated entry and destroy the signal.

**Validate before rendering.** The remaining checks are things a JSON schema cannot
express: `widths` summing to 1.0, `stats` values under ~10 *printed* characters
(entities are resolved first, so `13&ndash;16` counts as five), row/column arity,
at most two callouts. Structured outputs supports no numeric or length constraints at all,
so these live in `schema.guards()`. They warn and render anyway — a stray 11-character
stat is not worth burning a research run over.

**Watch page overflow.** `render` reports the estimated sheet count against the length you
asked for. The estimate is measured off rendered box heights rather than word counts —
tables and callouts cost far more than their word count suggests — and predicts the
printed page count exactly across the calibration documents. If you are one or two lines
over, dropping the least important block by hand is still easier than re-prompting.

**Long tables break across pages** with a repeating header, rather than being shunted whole
onto the next sheet. If you restyle anything, re-run `tools/measure.py` — the estimator's
constants are measured, not derived from the CSS.
