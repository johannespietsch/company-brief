"""Load the prompt pack and fill the user template."""

from __future__ import annotations

import re
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"

# The template uses a handlebars-ish {{var}} / {{#if x}}...{{/if}} syntax.
_IF_BLOCK = re.compile(r"\{\{#if\s+(\w+)\}\}(.*?)\{\{/if\}\}", re.DOTALL)
_VAR = re.compile(r"\{\{(\w+)\}\}")


def _read(name: str) -> str:
    text = (PROMPT_DIR / name).read_text(encoding="utf-8").strip()
    return text


# Only these sections of an outreach profile go to research. Tone and "never
# say" rules belong to the drafting step, not the research prompt.
_OFFER_SECTIONS = ("What he's good at", "What he's exploring")


def offer_from_profile(path: Path) -> str:
    """Pull the offering sections out of an outreach-profile markdown file."""
    text = Path(path).read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    picked = []
    for wanted in _OFFER_SECTIONS:
        match = next((s for s in sections if s.startswith(wanted)), None)
        if match is None:
            raise ValueError(f"{path}: no '## {wanted}...' section")
        lines = [ln for ln in match.strip().splitlines()
                 if not ln.startswith("**Prices")]
        picked.append("### " + "\n".join(lines))
    return "\n\n".join(picked)


def system_prompt() -> str:
    return _read("system_prompt.md")


def user_prompt(**fields: str) -> str:
    """Fill user_prompt_template.md. Unknown placeholders are left untouched so a
    template edit shows up in the output instead of vanishing silently."""
    template = _read("user_prompt_template.md")

    def keep_if_truthy(m: re.Match[str]) -> str:
        return m.group(2) if fields.get(m.group(1)) else ""

    filled = _IF_BLOCK.sub(keep_if_truthy, template)
    filled = _VAR.sub(lambda m: fields.get(m.group(1), m.group(0)), filled)
    return filled
