"""
Default configuration resolved from the plugin's bundled ``.env`` file.

The capstone notebook lives in a company-owned monorepo where committing
credentials is forbidden by policy, so the bundled defaults (currently a
spend-capped OpenRouter API key) are hosted in **this** plugin repo
instead. The notebook imports the resolver below; the literal key never
appears in the company repo.

Resolution order
----------------

For each defaulted value, the resolver checks (in order):

1. The corresponding **process environment variable** (e.g.
   ``OPENROUTER_API_KEY`` in ``os.environ``). This lets the marker
   override any default by setting an env var before launching Jupyter.
2. The **bundled ``.env`` file** shipped with the package (this directory).
3. ``None`` if neither is set.

The notebook also lets the marker override at the call site by
reassigning the variable in its configuration cell -- so there are three
overlapping override mechanisms, intentionally redundant.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load_dotenv(path: Path) -> dict[str, str]:
    """Tiny ``.env`` parser. ``KEY=value`` per line, ``#`` comments allowed."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


_BUNDLED: dict[str, str] = _load_dotenv(_ENV_PATH)


def default_openrouter_key() -> Optional[str]:
    """Resolve the OpenRouter API key for the bundled notebook.

    Resolution order: process environment variable
    (``OPENROUTER_API_KEY``) -> bundled ``.env`` -> ``None``.

    Returns ``None`` if no key is configured anywhere; the notebook
    treats that as a hard error and prompts the marker to supply one.
    """
    env_val = os.environ.get("OPENROUTER_API_KEY")
    if env_val:
        return env_val
    bundled = _BUNDLED.get("OPENROUTER_API_KEY")
    return bundled or None


def bundled_dotenv() -> dict[str, str]:
    """Return the raw contents of the bundled ``.env`` (debug/introspection)."""
    return dict(_BUNDLED)
