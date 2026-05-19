"""Tests for the knowledge-base bootstrap helper.

Mocks ``urllib.request.urlopen`` so the suite stays offline-safe.
"""

import io
import json
from unittest.mock import patch, MagicMock

from smart_street_lighting.rag import bootstrap_knowledge_base


def _fake_urlopen(responses):
    """Build an urlopen mock that returns the queued responses in order."""
    queue = list(responses)
    def _opener(url, timeout=None):
        payload = queue.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return MagicMock(
            __enter__=lambda self: io.BytesIO(payload),
            __exit__=lambda self, *a: False,
            read=lambda: payload,
        )
    return _opener


def test_bootstrap_downloads_missing_files(tmp_path):
    index = [
        {"type": "file", "name": "a.md", "download_url": "https://raw/a.md"},
        {"type": "file", "name": "b.md", "download_url": "https://raw/b.md"},
    ]
    fake = _fake_urlopen([
        json.dumps(index).encode(),
        b"# A\n",
        b"# B\n",
    ])
    with patch("urllib.request.urlopen", side_effect=fake):
        result = bootstrap_knowledge_base(
            repo="x/y", ref="main", path="kb", dest=tmp_path, log=None,
        )
    assert result["downloaded"] == 2
    assert result["kept"] == 0
    assert (tmp_path / "a.md").read_bytes() == b"# A\n"
    assert (tmp_path / "b.md").read_bytes() == b"# B\n"


def test_bootstrap_keeps_existing_files(tmp_path):
    (tmp_path / "a.md").write_bytes(b"local edit\n")
    index = [
        {"type": "file", "name": "a.md", "download_url": "https://raw/a.md"},
        {"type": "file", "name": "b.md", "download_url": "https://raw/b.md"},
    ]
    fake = _fake_urlopen([
        json.dumps(index).encode(),
        b"# B from remote\n",
    ])
    with patch("urllib.request.urlopen", side_effect=fake):
        result = bootstrap_knowledge_base(
            repo="x/y", ref="main", path="kb", dest=tmp_path, log=None,
        )
    assert result["downloaded"] == 1
    assert result["kept"] == 1
    # local file untouched
    assert (tmp_path / "a.md").read_bytes() == b"local edit\n"


def test_bootstrap_skips_non_files(tmp_path):
    # Directory entries (type="dir") and missing download_url must be skipped.
    index = [
        {"type": "dir",  "name": "sub",  "download_url": None},
        {"type": "file", "name": "real.md", "download_url": "https://raw/real.md"},
    ]
    fake = _fake_urlopen([
        json.dumps(index).encode(),
        b"real\n",
    ])
    with patch("urllib.request.urlopen", side_effect=fake):
        result = bootstrap_knowledge_base(
            repo="x/y", ref="main", path="kb", dest=tmp_path, log=None,
        )
    assert result["downloaded"] == 1
    assert not (tmp_path / "sub").exists()


def test_bootstrap_handles_github_failure_gracefully(tmp_path):
    fake = _fake_urlopen([RuntimeError("503 Service Unavailable")])
    with patch("urllib.request.urlopen", side_effect=fake):
        result = bootstrap_knowledge_base(
            repo="x/y", ref="main", path="kb", dest=tmp_path, log=None,
        )
    assert result == {"downloaded": 0, "kept": 0, "failed": []}
