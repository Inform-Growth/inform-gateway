
import asyncio
import json
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient
from starlette.applications import Starlette
from contextlib import asynccontextmanager

@asynccontextmanager
async def my_lifespan(server):
    print("User lifespan started")
    yield
    print("User lifespan ended")

mcp = FastMCP("test", lifespan=my_lifespan)

@mcp.prompt()
def hello(name: str) -> str:
    return f"Hello {name}"

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

async def check_all():
    # Setup
    mcp.streamable_http_app()
    mcp._setup_handlers()
    
    prompts = await mcp.list_prompts()
    tools = await mcp.list_tools()
    print("Prompts in FastMCP:", [p.name for p in prompts])
    print("Tools in FastMCP:", [t.name for t in tools])

    print("\n--- Checking Lifespan ---")
    async with mcp.session_manager.run():
        print("Inside run context")

if __name__ == "__main__":
    asyncio.run(check_all())
