"""
FastOMOP Web Interface

Exposes the FastOMOP workflow through AgentOS with built-in web UI.

Usage:
    uv run python -m agno_fastomop.web_interface

Then visit http://localhost:7777

Note: Auto-reload is disabled due to DuckDB file locking constraints.
"""


import asyncio
from contextlib import asynccontextmanager
from agno.os import AgentOS
from agno_fastomop.workflows.omop_workflow import initialize_workflow, cleanup_workflow
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import config
from agno.db.sqlite import SqliteDb
from agno.team import Team
import uvicorn

# Global storage
_workflow = None
_agents = None
_omop_team_conv = None
_omop_team_complex = None
_agent_os = None
_app = None


@asynccontextmanager
async def app_lifespan(app):
    """Handle graceful shutdown - cleanup MCP connections"""
    # Startup: nothing to do (workflow already initialized)
    yield
    # Shutdown: cleanup MCP subprocess to release DuckDB lock
    print("Shutting down FastOMOP - cleaning up MCP connections...")
    await cleanup_workflow()
    print("Cleanup complete")


async def initialize():
    """Initialize workflow and create AgentOS - all in the same event loop"""
    global _workflow, _agents, _omop_team, _agent_os, _app

    print("Initializing FastOMOP workflow...")
    _workflow = await initialize_workflow()
    _agents = [step.agent for step in _workflow.steps]
    print("✓ Workflow initialized")

    # Get default model config from config.local.toml
    team_model_config = {
        "MODEL_TYPE": config["models"]["default_provider"],
        "MODEL_ID": config["models"]["default_id"]
    }

    # Create shared memory db for all agents and team
    shared_db = SqliteDb(db_file="db_agent.db")

    # Update each agent to use the shared db
    for agent in _agents:
        agent.db = shared_db

    # Create a Team with both agents working together
    _omop_team_conv = Team(
        name="OMOP Conversation Team",
        model=create_model(team_model_config),
        members=_agents,
        db=shared_db,
        tool_call_limit=15,
        enable_user_memories=False,
        add_history_to_context=True,
        enable_session_summaries=True,
        add_session_summary_to_context=True,
        num_history_runs=3,
        search_session_history=False,
        share_member_interactions=True,
        compress_tool_results=True,
        stream=False,
        stream_member_events=True,
        show_members_responses=True,
        description="Team for OMOP clinical queries: semantic agent extracts concepts, database agent generates and executes SQL",
        instructions=[
            "You are coordinating a clinical database query team for OMOP CDM (Observational Medical Outcomes Partnership Common Data Model) queries.",
            "",
            "WORKFLOW (ALWAYS follow this exact sequence):",
            "1. FIRST: Delegate to 'OMOP Semantic Agent' to extract clinical concepts from the user's natural language query",
            "   - This agent will identify relevant OMOP concept IDs, domains, and vocabulary terms",
            "",
            "2. SECOND: Take the semantic context output and delegate to 'OMOP Database Agent'",
            "   - Pass both the original user query AND the semantic context",
            "   - This agent will generate OMOP CDM-compliant SQL and execute it",
            "",
            "3. FINALLY: Return the query results to the user in a clear, understandable format and explain the steps involved (derived concepts, logics etc from semantic context)",
            "",
            "IMPORTANT RULES:",
            "- NEVER skip the semantic agent - it provides crucial OMOP concept mappings",
            "- ALWAYS run agents sequentially in the order above (semantic → database)",
            "- Results have to be none 0, if you get 0 results, delegate again with refinement suggestions",
            "-For follow-ups, reference the session summary for prior context.",
        ],
    )

    # Create a Team with both agents working together
    _omop_team_complex = Team(
        name="OMOP Complex Team",
        model=create_model(team_model_config),
        members=_agents,
        db=shared_db,
        enable_user_memories=False,
        add_history_to_context=False,
        num_history_runs=0,
        share_member_interactions=True,
        search_session_history=False,
        compress_tool_results=True,
        stream=False,
        stream_member_events=True,
        show_members_responses=True,
        description="Team for OMOP complex clinical queries: semantic agent extracts concepts, database agent generates and executes SQL",
        instructions=[
            "You are coordinating a clinical database query team for OMOP CDM (Observational Medical Outcomes Partnership Common Data Model)"
            "",
            "WORKFLOW (ALWAYS follow this exact sequence):",
            "1. FIRST: Delegate to 'OMOP Semantic Agent' to extract clinical concepts from the user's natural language query",
            "   - This agent will identify relevant OMOP concept IDs, domains, and vocabulary terms",
            "",
            "2. SECOND: Take the semantic context output and delegate to 'OMOP Database Agent'",
            "   - Pass both the original user query AND the semantic context",
            "   - This agent will generate OMOP CDM-compliant SQL and execute it",
            "",
            "3. FINALLY: Return the query results to the user in a clear, understandable format and explain the steps involved (derived conceps, logics ect from semantic context",
            "",
            "IMPORTANT RULES:",
            "- NEVER skip the semantic agent - it provides crucial OMOP concept mappings",
            "- ALWAYS run agents sequentially in the order above (semantic → database)",
            "- Results have to be none 0, if you get 0 results, delegate again with refinement suggestions",
        ],
    )

    print("✓ Team created with both agents")

    # Create AgentOS with all three options:
    # - workflows: for cloud AgentOS UI
    # - teams: for local Agent UI (Team mode)
    # - agents: for local Agent UI (Agent mode - individual agents)
    _agent_os = AgentOS(
        name="FastOMOP",
        description="Natural language interface for OMOP clinical databases",
        workflows=[_workflow],    # Option 1: Full workflow (cloud UI)
        teams=[_omop_team_conv, _omop_team_complex],        # Option 2: Team (local UI - Team mode)
        agents=_agents,            # Option 3: Individual agents (local UI - Agent mode)
        lifespan=app_lifespan,
    )

    _app = _agent_os.get_app()
    print("✓ AgentOS created with workflow, team, and individual agents")


async def main():
    """Main async entry point"""
    # Initialize everything in this event loop
    await initialize()

    # Configure and run uvicorn server
    uvicorn_config = uvicorn.Config(
        app=_app,
        host="0.0.0.0",
        port=3000,
        reload=False,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)

    # Run server in the same event loop
    await server.serve()


if __name__ == "__main__":
    """Visit http://localhost:7777 to interact with FastOMOP"""
    asyncio.run(main())
