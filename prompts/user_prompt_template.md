Produce a company brief.

COMPANY: {{company_name}}
DISAMBIGUATION: {{country_city_or_url}}     # helps avoid same-name collisions
STANCE: {{stance}}                          # SUPPLIER | DEMAND | DUAL
LENGTH: {{page_count}} pages                # 2-5; the renderer targets A4
AUDIENCE CONTEXT: {{why_the_reader_cares}}  # e.g. "evaluating them as a delivery partner"
{{#if focus}}SPECIFIC FOCUS: {{focus}}{{/if}}
{{#if offer}}
## What the reader can offer

{{offer}}

Use this as a lens, not as content. When you look for openings and decide who to
list under "contacts", favour what this reader could credibly help with, and say
when the company shows no opening for it. Do not describe the reader or repeat
this material in the brief, and do not stretch the evidence to fit it.
{{/if}}

## Required content for this stance

### If STANCE is SUPPLIER — what they sell and how they stand
- At a glance: legal entity, HQ and offices, leadership, ownership, self-positioning
- Offerings: every product and service line, what each actually does
- Capabilities: technical range, and specifically what they market as differentiators
- Posture: technology and channel partnerships, and what those partnerships signal
- Who they work with: named references grouped by sector; published case studies
- Reading the posture: 3-5 interpretive points on strategy, direction and constraints

### If STANCE is DEMAND — what they need and what constrains them
- At a glance: legal entity, structure, HQ and sites, leadership, ownership
- Industries and customer base: who they serve, in what geographies
- Scale and figures: a table of metrics, each with source and date
- Corporate history: how the current structure was assembled, with dates
- Product or service portfolio
- Priorities and stated challenges: draw these from their OWN published output
  (blog, news, annual review, roadmap posts) wherever possible, and say so
- Unstated challenges: what the evidence implies that they have not said
- Implications for an external provider: where the concrete openings are

### If STANCE is DUAL — both, as two labelled parts
- Shared "At a glance" section covering identity and ownership
- PART A: the supplier sections above
- PART B: the demand sections above, framed as what THEY are up against
- A closing section on where the two stances collide or contradict each other
- Open questions worth verifying before engaging

## Who to write to (all stances)

Fill the "contacts" field with 1-3 people at the company who plausibly own the
problem behind the strongest opening you found (for DEMAND, the "Implications"
section; for SUPPLIER or DUAL, the partnership or collision point). Prefer the
person who owns the problem over the most senior person. Take names only from
sources you fetched: team and leadership pages, press releases, conference
programmes, the company's own posts. "why_them" ties the person to a specific
finding in this brief. Give a source_url for each person. Never include email
addresses or phone numbers, and never guess a name from a role. If no one can be
established, return an empty array and say what you could not find in "unverified".

## Regulatory and market context

Where the company operates in a regulated domain, establish the CURRENT state of the
relevant regulation by searching — do not rely on your training data, which may predate
amendments, deferrals or repeals. Give dates and cite the instrument.

Where relevant, establish the current market conditions for their sector: growth or
contraction, published survey data, demand signals.

## Output format

The API enforces the shape; the structure below says what each field is for.

Use HTML-style inline markup inside text fields: <b>, <i>, and HTML entities for special
characters (&amp;, &euro;, &ndash;, &rsquo;). Do not use markdown syntax inside field
values.

{
  "meta": {
    "company": "display name as it should appear as the title",
    "kicker": "ALL-CAPS category line, e.g. SUPPLIER BRIEF - AI ENGINEERING",
    "subtitle": "one line: what this covers, location, compile date",
    "compiled": "YYYY-MM-DD",
    "confidence": "high | medium | low",
    "confidence_note": "one sentence on what limits confidence, if anything"
  },
  "stats": [
    {"value": "380", "label": "Group employees"}
  ],
  "blocks": [
    {"type": "heading",  "text": "..."},
    {"type": "subheading", "text": "..."},
    {"type": "part",     "label": "PART A", "text": "Stance as a solutions provider"},
    {"type": "paragraph","text": "..."},
    {"type": "bullets",  "items": ["...", "..."]},
    {"type": "facts",    "rows": [["Label", "Value"]]},
    {"type": "table",    "header": ["Col A", "Col B"],
                         "rows": [["...", "..."]],
                         "widths": [0.3, 0.7]},
    {"type": "callout",  "title": "...", "text": "..."}
  ],
  "sources": "One paragraph naming the sources used, grouped by publisher, with dates for
              anything time-sensitive, plus a note on which figures are company-reported
              and where sources disagree.",
  "contacts": [
    {"name": "Full name as published", "role": "Title as published",
     "why_them": "one sentence tying them to a finding above",
     "source_url": "page you fetched that names them",
     "confidence": "high | medium | low  (is this the right owner, not is the name real)"}
  ],
  "unverified": [
    "Each material claim you could NOT confirm, and what you would need to confirm it."
  ]
}

Constraints on the output:
- 3-6 "stats" entries. Values must be short enough to render on one line.
- "widths" are fractions of the text column and must sum to 1.0.
- "facts" is for a two-column label/value block; "table" is for real tabular data.
- Use "callout" at most twice, for the single most important finding in each part.
- Aim the total content at {{page_count}} A4 pages at roughly 550 words per page,
  counting tables as their rendered height rather than their word count.
