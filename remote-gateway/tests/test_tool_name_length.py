"""Test that all built-in registered tool names fit within the client-safe length limit.

Does not import mcp_server (startup side effects). Instead registers each tool
module against a lightweight collector to capture names during registration.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

MAX_TOOL_NAME_LENGTH = 64  # must match mcp_server.MAX_TOOL_NAME_LENGTH


class _NameCollector:
    """Minimal FastMCP stand-in that captures tool names during registration."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def tool(self):
        def decorator(fn):
            self.names.append(fn.__name__)
            return fn
        return decorator

    def add_tool(self, fn, name=None, **kwargs):
        self.names.append(name or getattr(fn, "__name__", "unknown"))

    @property
    def name(self) -> str:
        return "test-gateway"


def _collect_builtin_tool_names() -> list[str]:
    from tools import apollo as _apollo_tools
    from tools import attio as _attio_tools
    from tools import email_tools as _email_tools
    from tools import meta as _meta_tools
    from tools import notes as _notes_tools
    from tools import registry as _registry_tools
    from tools import wiza as _wiza_tools
    from tools._core import onboarding as _onboarding_tools
    from tools._core import profile_manager as _profile_manager_tools
    from tools._core import skill_manager as _skill_manager_tools
    from tools._core import task_manager as _task_manager_tools
    from field_registry import registry

    collector = _NameCollector()
    mock_telemetry = MagicMock()
    mock_user_var = MagicMock()
    mock_user_var.get.return_value = None

    _meta_tools.register(collector, lambda: collector.name, mock_telemetry)
    _notes_tools.register(collector)
    _registry_tools.register(collector, registry)
    _attio_tools.register(collector)
    _email_tools.register(collector)
    _wiza_tools.register(collector)
    _apollo_tools.register(collector)
    _onboarding_tools.register(collector, mock_telemetry, mock_user_var)
    _skill_manager_tools.register(collector, mock_telemetry, mock_user_var)
    _profile_manager_tools.register(collector, mock_telemetry, mock_user_var)
    _task_manager_tools.register(collector, mock_telemetry, mock_user_var)

    return collector.names


def test_builtin_tool_names_within_limit():
    """All built-in tool names must be <= MAX_TOOL_NAME_LENGTH characters."""
    names = _collect_builtin_tool_names()
    violations = [n for n in names if len(n) > MAX_TOOL_NAME_LENGTH]
    assert not violations, (
        f"Tool names exceed {MAX_TOOL_NAME_LENGTH} chars: "
        + ", ".join(f"'{n}' ({len(n)})" for n in violations)
    )


def test_max_tool_name_length_constant_value():
    """Constant must be 64 — the client-safe threshold."""
    assert MAX_TOOL_NAME_LENGTH == 64


def test_all_builtin_names_collected():
    """Sanity check: registration produces a non-empty list of names."""
    names = _collect_builtin_tool_names()
    assert len(names) > 10, f"Expected >10 tool names, got {len(names)}: {names}"
