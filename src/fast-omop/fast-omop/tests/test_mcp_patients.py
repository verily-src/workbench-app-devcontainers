"""
Quick test script to query patient count via OMCP MCP server
"""
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_patient_count():
    """Test MCP connection and query patient count"""

    server_params = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "--directory",
            "/Users/k24118093/Documents/omcp_server",
            "python",
            "src/omcp/main.py"
        ],
        env={
            "DB_PATH": "/Users/k24118093/Documents/omcp_server/synthetic_data/synthea.duckdb"
        }
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("Connected to OMCP server")
            print("=" * 50)

            # Query patient count
            sql_query = "SELECT COUNT(*) as patient_count FROM base.person"

            result = await session.call_tool(
                "Select_Query",
                arguments={"query": sql_query}
            )

            print(f"SQL Query: {sql_query}")
            print("=" * 50)
            print("Result:")
            print(result.content[0].text)
            print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_patient_count())
