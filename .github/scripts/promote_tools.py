"""
promote_tools.py — AI-powered tool promotion script

Called by auto_promote.yml after a merge to main. For each new Python tool
in local-workspace/tools/, uses the Claude API to inject the function into
remote-gateway/core/mcp_server.py with the correct @mcp.tool() decorator
and validated() wrapper.

Usage (called by GitHub Action):
    python .github/scripts/promote_tools.py --changed-files "tools/a.py tools/b.py"

Environment variables required:
    ANTHROPIC_API_KEY   — for the Claude promotion call
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).parent.parent.parent
MCP_SERVER = REPO_ROOT / "remote-gateway" / "core" / "mcp_server.py"
FIELDS_SRC = REPO_ROOT / "local-workspace" / "context" / "fields"
FIELDS_DST = REPO_ROOT / "remote-gateway" / "context" / "fields"
TOOLS_SRC = REPO_ROOT / "local-workspace" / "tools"

PROMOTION_MARKER = "# Promoted tools go below this line."
ENTRYPOINT_MARKER = "if __name__ == \"__main__\":"

SYSTEM_PROMPT = """\
You are an expert Python engineer promoting a locally-developed tool into a \
centralized FastMCP gateway server.

You will receive:
1. A new Python tool function (from local-workspace/tools/).
2. The current contents of remote-gateway/core/mcp_server.py.
3. The integration name the tool belongs to (e.g., "stripe", "hubspot").

Your job:
- Extract the primary tool function(s) from the tool file.
- Add the @mcp.tool() decorator above each function.
- Wrap each function's return statement with validated("<integration>", <result>)
  so the field registry validates the response on every call.
- Insert the decorated function(s) into the server file immediately after the
  line that reads:
      # Promoted tools go below this line.
  and before the if __name__ == "__main__": block.
- Preserve every other line in the server file exactly — do not reformat,
  reorder, or change anything outside the insertion zone.
- Do not add import statements that are already present.
- Output ONLY the complete updated mcp_server.py content. No explanation, \
no markdown fences, no commentary.
"""


def infer_integration(tool_path: Path) -> str:
    """Best-effort: derive integration name from filename or paired skill."""
    stem = tool_path.stem  # e.g., "stripe_churn" → "stripe"
    parts = stem.split("_")
    candidate = parts[0]

    # Check if a matching field YAML exists
    if (FIELDS_SRC / f"{candidate}.yaml").exists():
        return candidate

    # Fall back to the first word of the filename
    return candidate


def promote_tool(tool_path: Path, client: anthropic.Anthropic) -> bool:
    """Promote a single tool file into mcp_server.py using Claude."""
    integration = infer_integration(tool_path)
    tool_code = tool_path.read_text()
    server_code = MCP_SERVER.read_text()

    # Skip if function already exists in the server
    func_name = _extract_first_def(tool_code)
    if func_name and f"def {func_name}" in server_code:
        print(f"  ↳ {tool_path.name}: already promoted (found def {func_name}), skipping.")
        return False

    print(f"  ↳ Promoting {tool_path.name} (integration: {integration}) via Claude...")

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Integration: {integration}\n\n"
                    f"--- Tool file ({tool_path.name}) ---\n{tool_code}\n\n"
                    f"--- Current mcp_server.py ---\n{server_code}"
                ),
            }
        ],
    )

    updated_server = message.content[0].text.strip()

    # Safety check: make sure the marker and entrypoint are still present
    if PROMOTION_MARKER not in updated_server or ENTRYPOINT_MARKER not in updated_server:
        print(f"  ✗ Claude returned unexpected output for {tool_path.name} — skipping.")
        return False

    MCP_SERVER.write_text(updated_server)
    print(f"  ✓ {tool_path.name} promoted successfully.")
    return True


def copy_field_yamls(changed_files: list[str]) -> list[str]:
    """Copy field YAML files from local-workspace to remote-gateway."""
    copied = []
    for f in changed_files:
        path = Path(f)
        if "local-workspace/context/fields" in str(path) and path.suffix == ".yaml":
            src = REPO_ROOT / path
            dst = FIELDS_DST / path.name
            if src.exists():
                FIELDS_DST.mkdir(parents=True, exist_ok=True)
                dst.write_text(src.read_text())
                print(f"  ✓ Copied field definition: {path.name}")
                copied.append(path.name)
    return copied


def _extract_first_def(code: str) -> str | None:
    """Extract the first function name defined in a Python source string."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("def "):
            return stripped.split("(")[0].replace("def ", "").strip()
    return None


def extract_env_vars(code: str) -> list[str]:
    """Scan a Python source file for os.environ references.

    Returns a sorted, deduplicated list of environment variable names the
    tool requires — so the admin knows exactly what to provision on the
    gateway server after promotion.

    Args:
        code: Python source code as a string.

    Returns:
        List of env var names (e.g., ["STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET"]).
    """
    import re

    patterns = [
        r'os\.environ\.get\(["\'](\w+)["\']',   # os.environ.get("KEY")
        r'os\.environ\[["\'](\w+)["\']\]',       # os.environ["KEY"]
        r'os\.getenv\(["\'](\w+)["\']',          # os.getenv("KEY")
    ]
    found = set()
    for pattern in patterns:
        found.update(re.findall(pattern, code))
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--changed-files",
        required=True,
        help="Space-separated list of changed file paths relative to repo root",
    )
    args = parser.parse_args()

    changed = args.changed_files.split()

    print("=== Field definition sync ===")
    copied_fields = copy_field_yamls(changed)
    if not copied_fields:
        print("  No new field definitions to copy.")

    print("\n=== Tool promotion ===")
    tool_files = [
        REPO_ROOT / f
        for f in changed
        if f.startswith("local-workspace/tools/") and f.endswith(".py")
    ]

    if not tool_files:
        print("  No new tool files to promote.")
        sys.exit(0)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    promoted = 0
    all_required_vars: list[str] = []

    for tool_path in tool_files:
        if tool_path.exists():
            required_vars = extract_env_vars(tool_path.read_text())
            if required_vars:
                all_required_vars.extend(required_vars)
            if promote_tool(tool_path, client):
                promoted += 1

    all_required_vars = sorted(set(all_required_vars))

    print(f"\n=== Done: {promoted} tool(s) promoted, {len(copied_fields)} field file(s) copied ===")

    if all_required_vars:
        print("\n=== ADMIN ACTION REQUIRED — provision these env vars on the gateway server ===")
        for var in all_required_vars:
            print(f"  export {var}=<value>")
        print(
            "\nAdd them to the gateway deployment environment before restarting the server.\n"
            "The promoted tools will fail at runtime until these are set."
        )


if __name__ == "__main__":
    main()
