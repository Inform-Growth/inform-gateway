#!/usr/bin/env python3
"""
MCP Local Proxy — Bridge for Claude Desktop.

Claude Desktop requires MCP servers to run as local processes using STDIO.
This proxy script runs locally and forwards all traffic to the remote Gateway
running on Railway via SSE (Server-Sent Events).

Usage (add to claude_desktop_config.json):
    "mcpServers": {
        "inform-gateway": {
            "command": "python3",
            "args": ["/path/to/proxy_server.py"],
            "env": {
                "GATEWAY_URL": "https://your-gateway.railway.app",
                "GATEWAY_API_KEY": "sk-your-key"
            }
        }
    }
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.sse import sse_client


async def run_proxy():
    """Forward STDIO to the remote Gateway SSE endpoint."""
    url = os.environ.get("GATEWAY_URL")
    api_key = os.environ.get("GATEWAY_API_KEY")

    if not url:
        print("Error: GATEWAY_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    # Normalize URL: ensure it includes /sse for the transport
    sse_url = f"{url.rstrip('/')}/sse"
    
    auth_headers = {}
    if api_key:
        auth_headers["Authorization"] = f"Bearer {api_key}"

    print(f"Connecting to remote gateway at {sse_url}...", file=sys.stderr)

    try:
        async with (
            sse_client(sse_url, headers=auth_headers) as (read, write, *_),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            print("Connected to remote gateway.", file=sys.stderr)

            # Bridging logic:
            # Since this script *is* the MCP server for Claude Desktop,
            # we need to act as a transparent proxy.
            # However, the mcp library's ClientSession is for *clients*.
            # To be a proxy, we need to read from sys.stdin and forward to 'write',
            # and read from 'read' and forward to sys.stdout.

            async def forward_to_remote():
                """Read from local stdin and write to remote Gateway."""
                while True:
                    line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    try:
                        data = json.loads(line)
                        await write.send(data)
                    except json.JSONDecodeError:
                        continue

            async def forward_to_local():
                """Read from remote Gateway and write to local stdout."""
                async for message in read:
                    sys.stdout.write(json.dumps(message) + "\n")
                    sys.stdout.flush()

            # Run both forwarding tasks
            await asyncio.gather(forward_to_remote(), forward_to_local())

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import contextlib
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_proxy())
