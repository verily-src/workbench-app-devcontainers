from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import get_agent_config, config
from agno_fastomop.agents.semantic import create_semantic_agent
from agno_fastomop.agents.database import create_database_agent
from agno.db.sqlite import SqliteDb
from pathlib import Path
import os


async def create_supervisor_agent(mcp_tools: MCPTools) -> Agent:
    """
    Create supervisor agent for orchestrating the semantic and database agents

    Args:
        mcp_tools: Shared MCP connection (to avoid DuckDB lock conflicts)
    """

    agent_config = get_agent_config("orchestrator")
    model = create_model(agent_config)

    # Shared database for conversation history and memory
    db = SqliteDb(db_file="db_agent.db")

    prompt_path = Path(__file__).parent.parent / "prompts" / "supervisor.txt"
    with open(prompt_path, 'r') as f:
        system_prompt = f.read()

    # Create sub-agents with shared MCP connection
    semantic_agent = create_semantic_agent(mcp_tools)
    database_agent = create_database_agent(mcp_tools)

    agent = Agent(
        name=agent_config["name"],
        model=model,
        instructions=system_prompt,
        db=db,  # Shared database for conversation history
        add_history_to_context=True,  # Enable conversation history
        enable_user_memories=True,  # Enable long-term memory
        tools=[semantic_agent, database_agent],  # Agents can be passed directly as tools
        knowledge=None,
        reasoning=agent_config.get("reasoning", True),
        markdown=agent_config.get("markdown", True),
    )
    return agent