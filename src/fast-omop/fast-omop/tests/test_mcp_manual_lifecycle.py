"""
Test manual MCP lifecycle management (connect once, reuse, close)
"""
import asyncio
from agno.tools.mcp import MCPTools
from agno.agent import Agent
from agno_fastomop.config import config
import os
from dotenv import load_dotenv

load_dotenv()


async def test_manual_lifecycle():
    """Test if we can connect once and reuse MCPTools across queries"""

    print("Creating MCPTools...")
    omcp_config = config["omcp"]
    mcp_tools = MCPTools(
        transport=omcp_config["transport"],
        command=omcp_config["command"],
        env={"DB_PATH": os.getenv("DB_PATH", "")}
    )

    print("Manually connecting MCP...")
    await mcp_tools._connect()

    print(f"Functions after connect: {list(mcp_tools.functions.keys())}")
    print("="*50)

    # Create agent with connected MCPTools
    from agno_fastomop.agents.factory import create_model
    from agno_fastomop.config import get_agent_config

    agent_config = get_agent_config("database")
    model = create_model(agent_config)

    agent = Agent(
        name="Test DB Agent",
        model=model,
        instructions="You execute SQL queries",
        tools=[mcp_tools],
    )

    # Query 1
    print("\nQuery 1: Count patients")
    print("-"*50)
    response1 = await agent.arun("Execute: SELECT COUNT(*) FROM base.person")
    print(response1.content)

    # Query 2 - reusing same agent/MCP connection
    print("\n" + "="*50)
    print("Query 2: Count visit occurrences")
    print("-"*50)
    response2 = await agent.arun("Execute: SELECT COUNT(*) FROM base.visit_occurrence")
    print(response2.content)

    print("\n" + "="*50)
    print("Closing MCP connection...")
    await mcp_tools.close()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(test_manual_lifecycle())
