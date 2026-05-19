"""
Knowledge-base bootstrap.

Syncs a directory of knowledge-base files from a GitHub repository
into a local destination. Idempotent: files already present locally
are kept as-is; only missing files are downloaded.

Used by the notebook to populate ``data/knowledge_base/`` on a fresh
checkout without committing the curated markdown twice (once in the
source repo, once in the notebook repo).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Callable, Optional


GITHUB_CONTENTS_API = "https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"


def bootstrap_knowledge_base(
    repo: str,
    ref: str,
    path: str,
    dest: Path | str,
    *,
    timeout: float = 30.0,
    log: Optional[Callable[[str], None]] = print,
) -> dict:
    """
    Sync a knowledge-base directory from GitHub into ``dest``.

    Always queries GitHub for the current file list, then for each
    entry:

    * if the file already exists locally, **keep it** (no download,
      no overwrite);
    * if the file is missing, **download it** from the raw URL.

    The function never deletes files. A file removed upstream stays
    in ``dest`` until manually cleaned up.

    Args:
        repo:    ``"owner/name"`` -- the GitHub repository slug.
        ref:     A branch name, tag, or commit SHA.
        path:    Path inside the repo whose contents should be synced.
        dest:    Local directory; created if it does not exist.
        timeout: Per-request timeout in seconds.
        log:     Optional logger; set to ``None`` for silent operation.

    Returns:
        ``{"downloaded": int, "kept": int, "failed": list[str]}``.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    api_url = GITHUB_CONTENTS_API.format(repo=repo, ref=ref, path=path)
    _log(f"Fetching KB index from {repo}@{ref}")
    try:
        with urllib.request.urlopen(api_url, timeout=timeout) as r:
            entries = json.load(r)
    except Exception as e:
        _log(f"  ! GitHub fetch failed: {e}")
        return {"downloaded": 0, "kept": 0, "failed": []}

    n_new = n_kept = 0
    failed: list[str] = []
    for entry in entries:
        if entry.get("type") != "file" or not entry.get("download_url"):
            continue
        name = entry["name"]
        target = dest / name
        if target.exists():
            n_kept += 1
            continue
        try:
            with urllib.request.urlopen(entry["download_url"], timeout=timeout) as f:
                target.write_bytes(f.read())
            n_new += 1
            _log(f"  + {name}")
        except Exception as err:
            failed.append(name)
            _log(f"  ! {name} failed: {err}")

    _log(f"KB ready at {dest}: {n_new} downloaded, {n_kept} kept local.")
    return {"downloaded": n_new, "kept": n_kept, "failed": failed}
