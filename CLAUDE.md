# CLAUDE.md: Agent Gateway

This file provides guidance to Claude Code when working in the **inform-gateway** repository.

# System Overview

The Agent Gateway is a centralized MCP server that hosts promoted tools for business integrations (Attio, Apollo, Exa, etc.) and provides a unified interface for AI agents. It operates under a **"Gateway First"** architecture where all agent interactions are governed, documented, and shadowed for proactive improvement.

## Core Commands

```bash
# Install (from repo root)
pip install -e .
pip install -e ".[dev]"   # includes pytest and ruff

# Lint & Test
ruff check .
pytest

# Run the Remote Gateway
# Local dev (stdio)
python remote-gateway/core/mcp_server.py

# Production (SSE — operators connect to this)
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py
```

## Primary Mandate: Gateway Operator

When acting as an agent in this environment, you MUST initialize your session by calling `get_operator_instructions` or using the `initialize-session` prompt. This activates your **Shadow Note-taking** and **Issue Logging** duties.

### Shadow Note-taking
- **Trigger**: After every significant task or discovery.
- **Action**: Call `write_note` to record the user's goal, the outcome, and whether the gateway did a "good job."
- **Persistence**: Notes are written to the dedicated "Write Notes" GitHub repository.

### Issue Logging
- **Trigger**: Auth failures, tool errors (4xx/5xx), or "noisy/raw" data.
- **Action**: Call `write_issue` to surface the problem to gateway administrators.

## Repository Structure

- **`remote-gateway/`** — The core infrastructure.
  - `core/` — FastMCP server and proxy logic.
  - `tools/` — Integration tools (Attio, Notes, Meta).
  - `prompts/` — System prompts and initialization logic.
- **`tests/`** — Verification for tools and proxy reliability.

## Coding Standards

- **Python 3.14+**. Strict type hints and comprehensive docstrings are required.
- **Docstrings are MCP descriptions**. Write them clearly for end-users.
- **No Hardcoded Credentials**. Use `os.environ` exclusively.
- **Read-Only by Default**. Mutating operations (POST, DELETE) require explicit admin approval in code review.
- **Field Registry**. Wrap all tool responses with `validated("<integration>", result)` to ensure field consistency and drift detection.
