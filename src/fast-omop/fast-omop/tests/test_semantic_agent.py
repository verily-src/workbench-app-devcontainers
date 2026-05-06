"""Test semantic agent in isolation to debug output format."""

import asyncio
import os
from agno.tools.mcp import MCPTools
from agno_fastomop.agents.semantic import create_semantic_agent
from agno_fastomop.config import config
from dotenv import load_dotenv

load_dotenv()

async def test_semantic_agent():
    """Test semantic agent with a complex drug query."""

    print("=" * 80)
    print("Testing Semantic Agent in Isolation")
    print("=" * 80)

    # Initialize MCP connection
    omcp_config = config["omcp"]
    mcp_tools = MCPTools(
        transport=omcp_config["transport"],
        command=omcp_config["command"],
        env={"DB_PATH": os.getenv("DB_PATH", "")}
    )

    print("\n1. Connecting to MCP...")
    await mcp_tools._connect()
    print("   ✓ MCP connected")

    # Create semantic agent
    print("\n2. Creating semantic agent...")
    semantic_agent = create_semantic_agent(mcp_tools)
    print("   ✓ Semantic agent created")

    # Test query
    test_query = "Counts of patients taking drug NDA020800 0.3 ML epinephrine 1 MG/ML Auto-Injector and loratadine 5 MG Chewable Tablet within 90 days."

    print(f"\n3. Running query:")
    print(f"   {test_query}")
    print()

    # Run the agent
    try:
        response = await semantic_agent.arun(test_query)

        print("\n4. Semantic Agent Response:")
        print("=" * 80)
        print(response)
        print("=" * 80)

        # Check if response is SemanticContext
        print("\n5. Response Analysis:")
        print(f"   Response Type: {type(response)}")

        if hasattr(response, 'content'):
            print(f"\n   Response.content:")
            print(f"   {response.content}")

        if hasattr(response, 'structured_output'):
            print(f"\n   Response.structured_output Type: {type(response.structured_output)}")
            so = response.structured_output
            if so:
                print(f"\n   Structured Output Details:")
                print(f"   - user_query: {getattr(so, 'user_query', 'N/A')}")
                print(f"   - query_intent: {getattr(so, 'query_intent', 'N/A')}")
                print(f"   - entities: {getattr(so, 'entities', 'N/A')}")
                print(f"   - temporal_constraint: {getattr(so, 'temporal_constraint', 'N/A')}")
                print(f"   - additional_filters: {getattr(so, 'additional_filters', 'N/A')}")

                if hasattr(so, 'entities') and so.entities:
                    print(f"\n   Entities breakdown:")
                    for i, entity in enumerate(so.entities):
                        print(f"     Entity {i+1}:")
                        print(f"       - term: {getattr(entity, 'term', 'N/A')}")
                        print(f"       - concept_id: {getattr(entity, 'concept_id', 'N/A')}")
                        print(f"       - concept_code: {getattr(entity, 'concept_code', 'N/A')}")
                        print(f"       - vocabulary_id: {getattr(entity, 'vocabulary_id', 'N/A')}")
                        print(f"       - domain_id: {getattr(entity, 'domain_id', 'N/A')}")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("\n6. Cleaning up...")
        if hasattr(mcp_tools, 'close'):
            await mcp_tools.close()
        print("   ✓ Done")

if __name__ == "__main__":
    asyncio.run(test_semantic_agent())
