"""
Test database agent standalone
"""
import asyncio
from agno_fastomop.agents.database import create_database_agent


async def test_database_agent():
    """Test database agent for SQL generation and execution"""

    print("Creating database agent...")
    async with create_database_agent() as agent:

        print("="*50)
        print("Testing database agent with patient count query")
        print("="*50)

        query = "Execute SQL: SELECT COUNT(*) FROM base.person"

        print(f"Query: {query}")
        print("="*50)

        response = await agent.arun(query)

        print("Response:")
        print(response.content)
        print("="*50)


if __name__ == "__main__":
    asyncio.run(test_database_agent())
