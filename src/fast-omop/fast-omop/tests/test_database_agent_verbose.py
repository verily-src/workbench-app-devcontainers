"""
Test database agent with verbose MCP tool inspection
"""
import asyncio
from agno_fastomop.agents.database import create_database_agent


async def test_database_agent_verbose():
    """Test database agent and inspect available tools"""

    print("Creating database agent...")
    agent = create_database_agent()

    print("="*50)
    print("Agent tools:")
    if hasattr(agent, 'tools'):
        for tool in agent.tools:
            print(f"  - {tool}")
            if hasattr(tool, 'functions'):
                print(f"    Functions: {list(tool.functions.keys())}")
    print("="*50)

    query = "Execute this SQL: SELECT COUNT(*) FROM base.person"

    print(f"Query: {query}")
    print("="*50)

    response = agent.run(query, stream=False)

    print("Response:")
    print(response.content)
    print("="*50)

    print("\nMessages:")
    for msg in response.messages:
        print(f"  Role: {msg.role}")
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            print(f"  Tool calls: {msg.tool_calls}")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(test_database_agent_verbose())
