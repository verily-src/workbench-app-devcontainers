from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.knowledge import Knowledge
from typing import Dict
from pathlib import Path
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import get_agent_config, config
from agno.vectordb.lancedb import LanceDb
from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder
from agno.db.sqlite import SqliteDb
from agno_fastomop.schemas.schemas import SemanticContext
import os


def create_database_agent(mcp_tools: MCPTools) -> Agent:
    """
    Create omop database agent with shared MCP connection

    Args:
        mcp_tools: Shared MCP connection (to avoid DB lock conflicts)

    Returns:
        Agent: Agno agent for omop db queries
    """

    agent_config = get_agent_config("database")
    model = create_model(agent_config)
    db = SqliteDb(db_file="db_agent.db")

    prompt_path = Path(__file__).parent.parent / "prompts" / "database_agent.txt"
    with open(prompt_path, 'r') as f:
        system_prompt = f.read()

    knowledge_path = Path(__file__).parent.parent / "knowledge" / "omop_world_model"
    # Use same embedder as bootstrap (lightweight, 384 dim)
    embedder = SentenceTransformerEmbedder(id="sentence-transformers/all-MiniLM-L6-v2")
    vectordb = LanceDb(
        uri=str(knowledge_path / ".lancedb"),
        table_name="omop_world_model",
        embedder=embedder,
    )
    knowledge = Knowledge(
        vector_db=vectordb,
        max_results=2,  # Reduced from 5 to speed up context processing
    )

    #Create agent with connected MCP tools
    agent = Agent(
        name=agent_config["name"],
        model=model,
        instructions=system_prompt,
        db=db,
        enable_user_memories=True,
        add_history_to_context=True,  # Enable conversation history
        tools=[mcp_tools],
        knowledge=knowledge,
        # No input_schema - the workflow passes previous step output as message content
        # No output_schema - return natural language for final answer
        # session_state only for JSON-serializable data
        session_state= {
            "agent_type": "database_agent",
        },
        reasoning=agent_config.get("reasoning", True),
        markdown=agent_config.get("markdown", True),
    )

    return agent
