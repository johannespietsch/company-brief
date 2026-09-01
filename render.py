"""Render a validated brief to a standalone A4-print HTML file."""

from __future__ import annotations

import re
from html import escape, unescape

# Text fields carry HTML-style inline markup (<b>, <i>) and HTML entities, so
# they must not be blanket-escaped. Keep an allowlist of inline tags, escape
# every other tag whole, and leave "&" alone so &euro; &ndash; &rsquo; survive.
# A tag, or a lone "<" that never formed one. Alternation order matters: the
# tag branch is tried first, so "<b>" is a tag and a bare "5 < 6" is not.
_TOKEN = re.compile(r"<[^<>]*>|<")
_ALLOWED_TAG = re.compile(r"</?(?:b|i|em|strong|sup|sub|br)\s*/?>", re.IGNORECASE)


def inline(text: str) -> str:
    def keep_or_escape(m: re.Match[str]) -> str:
        tag = m.group(0)
        if _ALLOWED_TAG.fullmatch(tag):
            return tag
        return tag.replace("<", "&lt;").replace(">", "&gt;")

    return _TOKEN.sub(keep_or_escape, str(text))


def plain(text: str) -> str:
    """Tag-stripped text, for word counting."""
    return re.sub(r"<[^>]*>", "", str(text))


def display_len(text: str) -> int:
    """Length as printed: tags stripped, entities resolved.

    "13&ndash;16" is eleven source characters and five printed ones. The stat
    guard is about what fits in the column, so it counts printed ones.
    """
    return len(unescape(plain(text)))


# --- page estimate -----------------------------------------------------------
# Measured against headless Chrome at this stylesheet, 178mm text column. These
# are read off rendered box heights, not derived from the CSS -- re-measure with
# tools/measure.py if you change the styling.
PAGE_MM = 297 - 18 - 16      # A4 minus the @page margins
LINE_MM = 5.82               # 11pt / 1.5
LINE_MM_SMALL = 4.60         # 9pt / 1.45, the footer
BLOCK_MM = 1.58              # bottom margin on a text block or list item
WPL = 20                     # words per line, full 178mm column at 11pt
WPL_LIST = 19                # list items are indented
WPL_SMALL = 24               # 9pt footer text

FIXED_MM = {
    "masthead": 48.8,        # kicker, title, subtitle, confidence, empty footer
    "stats": 20.4,           # one flex row; height does not depend on the count
    "heading": 13.8,
    "subheading": 9.3,
    "part": 21.0,
    "callout": 20.5,         # one-line callout including title and padding
    "facts_row": 7.94,
    "facts": 1.6,
    "table_row": 7.94,
    "table": 8.4,            # header row plus bottom margin
    "avoid_slack": 4.0,      # break-inside:avoid wastes space at a page break
}


def _text_mm(text, wpl=WPL, line=LINE_MM) -> float:
    words = len(plain(text).split())
    return BLOCK_MM + max(1, -(-words // wpl)) * line


def estimate_mm(data: dict) -> float:
    f = FIXED_MM
    mm = f["masthead"]
    if data.get("stats"):
        mm += f["stats"]

    for block in data.get("blocks", []):
        kind = block.get("type")
        if kind in ("heading", "subheading", "part"):
            mm += f[kind] + (f["avoid_slack"] if kind == "part" else 0)
        elif kind == "paragraph":
            mm += _text_mm(block.get("text", ""))
        elif kind == "callout":
            extra = max(0, len(plain(block.get("text", "")).split()) - 15)
            mm += f["callout"] + (extra / WPL) * LINE_MM + f["avoid_slack"]
        elif kind == "bullets":
            mm += sum(_text_mm(i, WPL_LIST) for i in block.get("items", []))
        elif kind == "facts":
            mm += f["facts"] + len(block.get("rows", [])) * f["facts_row"]
        elif kind == "table":
            # Tables break across pages, so no unbreakable slack.
            mm += f["table"] + len(block.get("rows", [])) * f["table_row"]

    if data.get("contacts"):
        mm += FIXED_MM["heading"] + FIXED_MM["table"]
        mm += len(data["contacts"]) * FIXED_MM["table_row"]

    mm += _text_mm(data.get("sources", ""), WPL_SMALL, LINE_MM_SMALL)
    for item in data.get("unverified", []):
        mm += _text_mm(item, WPL_SMALL, LINE_MM_SMALL)
    return mm


# Flow height alone under-predicts sheets: unbreakable blocks, widows and orphans
# waste space at each break. Measured at ~5% across the calibration documents.
BREAK_WASTE = 1.05


def estimate_pages(data: dict) -> float:
    """Sheets the brief will print on, as a fraction. Accurate to about +/-1
    sheet -- it is a warning aid, not a layout engine."""
    return estimate_mm(data) * BREAK_WASTE / PAGE_MM


# --- blocks ------------------------------------------------------------------

def _cells(row, tag="td"):
    return "".join(f"<{tag}>{inline(c)}</{tag}>" for c in row)


def _block_html(block: dict) -> str:
    kind = block.get("type")
    if kind == "heading":
        return f"<h2>{inline(block['text'])}</h2>"
    if kind == "subheading":
        return f"<h3>{inline(block['text'])}</h3>"
    if kind == "part":
        return (
            '<div class="part">'
            f'<span class="part-label">{inline(block["label"])}</span>'
            f'<span class="part-text">{inline(block["text"])}</span></div>'
        )
    if kind == "paragraph":
        return f"<p>{inline(block['text'])}</p>"
    if kind == "bullets":
        items = "".join(f"<li>{inline(i)}</li>" for i in block.get("items", []))
        return f"<ul>{items}</ul>"
    if kind == "facts":
        rows = "".join(
            f'<tr><th scope="row">{inline(r[0])}</th>'
            f"<td>{inline(r[1]) if len(r) > 1 else ''}</td></tr>"
            for r in block.get("rows", [])
        )
        return f'<table class="facts">{rows}</table>'
    if kind == "table":
        header = block.get("header", [])
        widths = block.get("widths", [])
        cols = "".join(
            f'<col style="width:{w * 100:.4g}%">'
            for w in (widths if len(widths) == len(header) else [])
        )
        rows = "".join(f"<tr>{_cells(r)}</tr>" for r in block.get("rows", []))
        return (
            f'<table class="data"><colgroup>{cols}</colgroup>'
            f"<thead><tr>{_cells(header, 'th')}</tr></thead><tbody>{rows}</tbody></table>"
        )
    if kind == "callout":
        return (
            '<aside class="callout">'
            f'<p class="callout-title">{inline(block["title"])}</p>'
            f"<p>{inline(block['text'])}</p></aside>"
        )
    return f"<!-- unrecognised block type: {escape(str(kind))} -->"


def _contacts_html(contacts: list[dict]) -> str:
    if not contacts:
        return ""
    rows = "".join(
        "<tr>"
        f"<td><b>{inline(c.get('name', ''))}</b><br>{inline(c.get('role', ''))}</td>"
        f"<td>{inline(c.get('why_them', ''))}</td>"
        f'<td><a href="{escape(c.get("source_url", ""), quote=True)}">source</a>'
        f" &middot; {inline(c.get('confidence', '?'))}</td>"
        "</tr>"
        for c in contacts
    )
    head = _cells(["Person", "Why them", "Basis"], "th")
    return (
        "\n<h2>Who to write to</h2>"
        '<table class="data"><colgroup><col style="width:28%">'
        '<col style="width:52%"><col style="width:20%"></colgroup>'
        f"<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
    )


CSS = """
@page { size: A4; margin: 18mm 16mm 16mm; }
:root { --ink:#16181d; --mute:#5c6270; --rule:#d8dbe2; --accent:#1c3f66; --wash:#f4f6f9; }
* { box-sizing: border-box; }
body { margin:0; background:#e9ebef; color:var(--ink);
  font:11pt/1.5 "Charter","Georgia","Times New Roman",serif; }
.sheet { max-width:190mm; margin:12mm auto; padding:18mm 16mm; background:#fff;
  box-shadow:0 1px 3px rgba(0,0,0,.16); }
header { border-bottom:2px solid var(--ink); padding-bottom:10px; margin-bottom:6px; }
.kicker { font:600 8.5pt/1.3 ui-sans-serif,-apple-system,"Helvetica Neue",sans-serif;
  letter-spacing:.14em; color:var(--accent); margin:0 0 6px; }
h1 { font-size:23pt; line-height:1.12; margin:0 0 6px; letter-spacing:-.01em; }
.subtitle { color:var(--mute); font-size:9.5pt; margin:0 0 4px; }
.confidence { font:9pt/1.45 ui-sans-serif,-apple-system,sans-serif; color:var(--mute);
  margin:8px 0 0; padding-top:8px; border-top:1px solid var(--rule); }
.confidence b { color:var(--ink); text-transform:uppercase; letter-spacing:.06em;
  font-size:8pt; }
.stats { display:flex; flex-wrap:wrap; gap:0; margin:14px 0 20px;
  border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); }
.stat { flex:1 1 0; min-width:78px; padding:10px 12px 9px;
  border-left:1px solid var(--rule); }
.stat:first-child { border-left:0; padding-left:0; }
.stat-value { font:600 17pt/1 ui-sans-serif,-apple-system,sans-serif;
  letter-spacing:-.02em; white-space:nowrap; }
.stat-label { font:9pt/1.3 ui-sans-serif,-apple-system,sans-serif; color:var(--mute);
  margin-top:4px; }
h2 { font-size:13.5pt; margin:20px 0 7px; padding-bottom:4px;
  border-bottom:1px solid var(--rule); break-after:avoid; }
h3 { font-size:10.5pt; margin:14px 0 5px; color:var(--accent);
  font-family:ui-sans-serif,-apple-system,sans-serif; break-after:avoid; }
p { margin:0 0 8px; }
ul { margin:0 0 10px; padding-left:17px; }
li { margin-bottom:4px; }
.part { margin:24px 0 10px; padding:9px 12px; background:var(--accent); color:#fff;
  break-after:avoid; break-inside:avoid; }
.part-label { font:700 8.5pt/1 ui-sans-serif,-apple-system,sans-serif;
  letter-spacing:.14em; display:block; opacity:.75; margin-bottom:3px; }
.part-text { font-size:11.5pt; }
table { width:100%; border-collapse:collapse; margin:0 0 12px; font-size:9.5pt; }
/* Let long tables flow across pages rather than shunting whole onto the next
   one; repeat the header and never split a row. */
thead { display:table-header-group; }
tr { break-inside:avoid; }
.data th, .data td { text-align:left; vertical-align:top; padding:5px 8px 5px 0;
  border-bottom:1px solid var(--rule); }
.data thead th { border-bottom:1.5px solid var(--ink);
  font:600 8.5pt/1.3 ui-sans-serif,-apple-system,sans-serif;
  text-transform:uppercase; letter-spacing:.06em; }
.facts th, .facts td { text-align:left; vertical-align:top; padding:5px 8px 5px 0;
  border-bottom:1px solid var(--rule); }
.facts th { width:30%; font-weight:600; color:var(--mute);
  font-family:ui-sans-serif,-apple-system,sans-serif; font-size:9pt; }
.callout { margin:14px 0; padding:11px 14px; background:var(--wash);
  border-left:3px solid var(--accent); break-inside:avoid; }
.callout p { margin:0; font-size:10pt; }
.callout-title { font:600 9pt/1.3 ui-sans-serif,-apple-system,sans-serif;
  letter-spacing:.04em; text-transform:uppercase; color:var(--accent);
  margin-bottom:4px !important; }
footer { margin-top:26px; padding-top:12px; border-top:2px solid var(--ink);
  font-size:9pt; color:var(--mute); }
footer h2 { font-size:9pt; text-transform:uppercase; letter-spacing:.08em;
  border:0; margin:0 0 5px; padding:0; color:var(--ink);
  font-family:ui-sans-serif,-apple-system,sans-serif; }
footer section + section { margin-top:14px; }
footer ul { padding-left:16px; }
@media print {
  body { background:#fff; }
  .sheet { max-width:none; margin:0; padding:0; box-shadow:none; }
}
"""


def render(data: dict) -> str:
    meta = data.get("meta", {})
    stats = "".join(
        f'<div class="stat"><div class="stat-value">{inline(s.get("value", ""))}</div>'
        f'<div class="stat-label">{inline(s.get("label", ""))}</div></div>'
        for s in data.get("stats", [])
    )
    blocks = "\n".join(_block_html(b) for b in data.get("blocks", []))
    blocks += _contacts_html(data.get("contacts", []))
    unverified = "".join(f"<li>{inline(u)}</li>" for u in data.get("unverified", []))
    note = meta.get("confidence_note", "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(plain(meta.get("company", "Company brief")))}</title>
<style>{CSS}</style></head>
<body><article class="sheet">
<header>
  <p class="kicker">{inline(meta.get("kicker", ""))}</p>
  <h1>{inline(meta.get("company", ""))}</h1>
  <p class="subtitle">{inline(meta.get("subtitle", ""))}</p>
  <p class="confidence"><b>Confidence: {inline(meta.get("confidence", "?"))}</b>
     {"&mdash; " + inline(note) if note else ""}</p>
</header>
{f'<div class="stats">{stats}</div>' if stats else ""}
{blocks}
<footer>
  <section><h2>Sources</h2><p>{inline(data.get("sources", ""))}</p></section>
  {f"<section><h2>Not verified</h2><ul>{unverified}</ul></section>" if unverified else ""}
</footer>
</article></body></html>
"""
