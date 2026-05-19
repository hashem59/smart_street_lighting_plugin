"""Tests for the bundled-default resolver."""

import os
import importlib
from pathlib import Path
from unittest.mock import patch


def test_loader_parses_dotenv_format(tmp_path):
    """Comments + blank lines + quoted values must round-trip cleanly."""
    from smart_street_lighting._defaults import _load_dotenv

    p = tmp_path / ".env"
    p.write_text(
        "# leading comment\n"
        "\n"
        "OPENROUTER_API_KEY=sk-or-v1-test\n"
        'QUOTED_DOUBLE="hello"\n'
        "QUOTED_SINGLE='world'\n"
        "  KEY_WITH_SPACES  =  v1  \n"
    )
    out = _load_dotenv(p)
    assert out["OPENROUTER_API_KEY"] == "sk-or-v1-test"
    assert out["QUOTED_DOUBLE"] == "hello"
    assert out["QUOTED_SINGLE"] == "world"
    assert out["KEY_WITH_SPACES"] == "v1"


def test_loader_missing_file_returns_empty(tmp_path):
    from smart_street_lighting._defaults import _load_dotenv
    assert _load_dotenv(tmp_path / "does-not-exist.env") == {}


def test_env_var_overrides_bundled():
    """OS env var beats the bundled .env value."""
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-from-env"}, clear=False):
        import smart_street_lighting._defaults as d
        importlib.reload(d)
        assert d.default_openrouter_key() == "sk-or-v1-from-env"


def test_bundled_env_resolves_when_env_var_absent():
    """No env var -> falls back to the bundled .env."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENROUTER_API_KEY", None)
        import smart_street_lighting._defaults as d
        importlib.reload(d)
        key = d.default_openrouter_key()
        # bundled key in this checkout exists and starts with sk-or-
        assert key is not None
        assert key.startswith("sk-or-")


def test_top_level_export():
    """default_openrouter_key is exported from the top-level package."""
    from smart_street_lighting import default_openrouter_key, bundled_dotenv
    assert callable(default_openrouter_key)
    assert isinstance(bundled_dotenv(), dict)


def test_dotenv_ships_with_package():
    """The .env file must live INSIDE the package so it's picked up by pip install."""
    import smart_street_lighting
    pkg_dir = Path(smart_street_lighting.__file__).resolve().parent
    assert (pkg_dir / ".env").exists()
