"""Shared Anthropic client construction.

Identity-linked API keys must name the workspace the request acts in, so the
key alone is not enough -- set ANTHROPIC_WORKSPACE_ID alongside it. Find it in
the Console under Settings -> Workspaces; it is in the URL and looks like
`wrkspc_...`. Keys that are not identity-linked ignore the header.
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic

ENV_PATH = Path(__file__).parent / ".env"


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Minimal .env loader. The SDK reads the environment, not a file; an
    existing environment variable always wins over the file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def credentials_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_client() -> anthropic.Anthropic:
    load_dotenv()
    headers = {}
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    return anthropic.Anthropic(default_headers=headers or None)
