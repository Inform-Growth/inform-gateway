"""
Validate the google-analytics entry in mcp_connections.json.

Run with:
    pytest remote-gateway/tests/test_google_analytics_config.py -v
"""
import json
from pathlib import Path

import pytest

CONNECTIONS_FILE = Path(__file__).parent.parent / "mcp_connections.json"

EXPECTED_TOOLS = [
    "run_report",
    "run_realtime_report",
    "run_funnel_report",
    "get_account_summaries",
    "get_property_details",
    "get_custom_dimensions_and_metrics",
    "list_google_ads_links",
]


def _load_ga() -> dict:
    """Load and return the google-analytics connection entry from mcp_connections.json.

    Calls pytest.fail() immediately if the config file is missing or the
    google-analytics key is absent, producing a clear FAILED result rather than an error.
    """
    if not CONNECTIONS_FILE.exists():
        pytest.fail(f"Config file not found: {CONNECTIONS_FILE}")
    data = json.loads(CONNECTIONS_FILE.read_text())
    if "google-analytics" not in data.get("connections", {}):
        pytest.fail("No 'google-analytics' entry found in connections — was it removed?")
    return data["connections"]["google-analytics"]


def test_google_analytics_uses_stdio_transport():
    ga = _load_ga()
    assert ga["transport"] == "stdio", (
        f"Expected 'stdio', got '{ga.get('transport')}'. "
        "analytics-mcp is a subprocess — must use stdio transport."
    )


def test_google_analytics_command_is_uvx():
    ga = _load_ga()
    assert ga.get("command") == "uvx", (
        f"Expected command 'uvx', got '{ga.get('command')}'. "
        "uvx is already installed in the Dockerfile and is the correct runner."
    )


def test_google_analytics_args_are_analytics_mcp():
    ga = _load_ga()
    assert ga.get("args") == ["analytics-mcp"], (
        f"Expected args ['analytics-mcp'], got {ga.get('args')}."
    )


def test_google_analytics_env_has_credentials():
    ga = _load_ga()
    env = ga.get("env", {})
    assert "GOOGLE_APPLICATION_CREDENTIALS" in env, (
        f"Expected GOOGLE_APPLICATION_CREDENTIALS in env, got: {list(env.keys())}"
    )


def test_google_analytics_credentials_is_interpolated():
    ga = _load_ga()
    env = ga.get("env", {})
    expected = "${GOOGLE_APPLICATION_CREDENTIALS}"
    assert env.get("GOOGLE_APPLICATION_CREDENTIALS") == expected, (
        f"Expected '{expected}', got: {env.get('GOOGLE_APPLICATION_CREDENTIALS')}"
    )


def test_google_analytics_has_tools_allow_list():
    ga = _load_ga()
    tools = ga.get("tools", {})
    assert "allow" in tools, (
        "Expected 'tools.allow' in google-analytics config — allowlist enforces read-only access."
    )


def test_google_analytics_allow_list_contains_expected_tools():
    ga = _load_ga()
    allow = ga.get("tools", {}).get("allow", [])
    assert set(allow) == set(EXPECTED_TOOLS), (
        f"Allow list must be exactly {EXPECTED_TOOLS}, got: {allow}. "
        "This prevents accidentally adding write tools."
    )
