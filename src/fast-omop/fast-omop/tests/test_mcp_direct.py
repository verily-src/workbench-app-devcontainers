"""
Test MCP connection directly without agent
"""
import asyncio
from agno.tools.mcp import MCPTools
import os
from dotenv import load_dotenv

load_dotenv()


async def test_mcp_direct():
    """Test MCP tools initialization"""

    print("Creating MCPTools...")
    mcp_tools = MCPTools(
        transport="stdio",
        command="uv run --directory /Users/k24118093/Documents/omcp_server python src/omcp/main.py",
        env={"DB_PATH": os.getenv("DB_PATH", "")}
    )

    print("="*50)
    print("MCPTools created, checking functions...")
    print(f"Functions before init: {list(mcp_tools.functions.keys())}")
    print("="*50)

    async with mcp_tools as tools:
        print("MCPTools initialized via context manager")
        print(f"Functions after init: {list(tools.functions.keys())}")
        print("="*50)

        if tools.functions:
            print("Available tools:")
            for name, func in tools.functions.items():
                print(f"  - {name}: {func.description}")
            print("="*50)


if __name__ == "__main__":
    asyncio.run(test_mcp_direct())
