"""
Validate that the attio entry in mcp_connections.json uses stdio transport
with the expected command and env structure (no OAuth blocks).

Run with:
    pytest remote-gateway/tests/test_attio_config.py -v
"""
import json
from pathlib import Path

import pytest

CONNECTIONS_FILE = Path(__file__).parent.parent / "mcp_connections.json"


def _load_attio() -> dict:
    """Load and return the attio connection entry from mcp_connections.json.

    Calls pytest.fail() immediately if the config file is missing or the
    attio key is absent, producing a clear FAILED result rather than an error.
    """
    if not CONNECTIONS_FILE.exists():
        pytest.fail(f"Config file not found: {CONNECTIONS_FILE}")
    data = json.loads(CONNECTIONS_FILE.read_text())
    if "attio" not in data.get("connections", {}):
        pytest.fail("No 'attio' entry found in connections — was it removed?")
    return data["connections"]["attio"]


def test_attio_uses_stdio_transport():
    attio = _load_attio()
    assert attio["transport"] == "stdio", (
        f"Expected 'stdio', got '{attio.get('transport')}'. "
        "The attio connection must use stdio, not http."
    )


def test_attio_command_is_npx():
    attio = _load_attio()
    assert attio.get("command") == "npx", (
        f"Expected command 'npx', got '{attio.get('command')}'"
    )


def test_attio_args_include_attio_mcp():
    attio = _load_attio()
    assert "attio-mcp" in attio.get("args", []), (
        f"Expected 'attio-mcp' in args, got: {attio.get('args')}"
    )


def test_attio_env_has_api_key_key():
    attio = _load_attio()
    env = attio.get("env", {})
    assert "ATTIO_API_KEY" in env, (
        f"Expected ATTIO_API_KEY in env, got keys: {list(env.keys())}"
    )


def test_attio_env_api_key_is_interpolated():
    attio = _load_attio()
    env = attio.get("env", {})
    assert env.get("ATTIO_API_KEY") == "${ATTIO_API_KEY}", (
        f"Expected '${{ATTIO_API_KEY}}', got: {env.get('ATTIO_API_KEY')}"
    )


def test_attio_has_no_oauth_block():
    attio = _load_attio()
    assert "oauth" not in attio, (
        "Found 'oauth' block in attio config — OAuth must be removed."
    )


def test_attio_has_no_headers_block():
    attio = _load_attio()
    assert "headers" not in attio, (
        "Found 'headers' block in attio config — HTTP headers must be removed."
    )


def test_attio_has_no_url():
    attio = _load_attio()
    assert "url" not in attio, (
        "Found 'url' in attio config — HTTP URL must be removed."
    )


# ---------------------------------------------------------------------------
# Apollo migration validation
# ---------------------------------------------------------------------------


def _load_apollo() -> dict:
    """Load and return the apollo connection entry from mcp_connections.json.

    Calls pytest.fail() immediately if the config file is missing or the
    apollo key is absent, producing a clear FAILED result rather than an error.
    """
    if not CONNECTIONS_FILE.exists():
        pytest.fail(f"Config file not found: {CONNECTIONS_FILE}")
    data = json.loads(CONNECTIONS_FILE.read_text())
    if "apollo" not in data.get("connections", {}):
        pytest.fail("No 'apollo' entry found in connections")
    return data["connections"]["apollo"]


def test_apollo_uses_http_transport():
    """Apollo uses http transport."""
    apollo = _load_apollo()
    assert apollo.get("transport") == "http", (
        f"Expected 'http', got '{apollo.get('transport')}'"
    )


def test_apollo_auth_type_is_oauth():
    """Apollo auth.type is 'oauth'."""
    apollo = _load_apollo()
    assert apollo.get("auth", {}).get("type") == "oauth", (
        "Apollo auth.type must be 'oauth'"
    )


def test_apollo_auth_has_access_token():
    """Apollo auth block has access_token with correct env var reference."""
    apollo = _load_apollo()
    assert apollo.get("auth", {}).get("access_token") == "${APOLLO_ACCESS_TOKEN}", (
        f"Expected '${{APOLLO_ACCESS_TOKEN}}', got: {apollo.get('auth', {}).get('access_token')}"
    )


def test_apollo_has_no_top_level_headers():
    """Apollo must not have a top-level 'headers' key."""
    apollo = _load_apollo()
    assert "headers" not in apollo, (
        "Apollo must not have a top-level 'headers' key — auth moved to auth block"
    )


def test_apollo_has_no_top_level_oauth():
    """Apollo must not have a top-level 'oauth' key."""
    apollo = _load_apollo()
    assert "oauth" not in apollo, (
        "Apollo must not have a top-level 'oauth' key — auth moved to auth block"
    )
