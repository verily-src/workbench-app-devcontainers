from agno.workflow import Workflow, Step
from agno.tools.mcp import MCPTools
from agno.compression.manager import CompressionManager
from agno_fastomop.agents.semantic import create_semantic_agent
from agno_fastomop.agents.database import create_database_agent
from agno_fastomop.agents.supervisor import create_supervisor_agent
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import config, get_agent_config
from agno_fastomop.observability.trace_context import write_trace_context_otel, clear_trace_context
from agno.db.sqlite import SqliteDb
from langfuse import observe, Langfuse, get_client
import asyncio
import os
import json

# Module-level storage for workflow (created once, reused)
# We cache separate workflows for batch vs interactive mode
_omop_workflow_interactive = None
_omop_workflow_batch = None
_mcp_tools = None
_init_lock = asyncio.Lock()


async def initialize_workflow(batch_mode=False):
    """
    Initialize Workflow with semantic -> database pipeline.
    FastOMOP approach: ONE shared MCP connection for both agents.

    Args:
        batch_mode: If True, disables workflow history for performance (queries are independent)
    """
    global _omop_workflow_interactive, _omop_workflow_batch, _mcp_tools

    async with _init_lock:
        # Return the appropriate cached workflow based on mode
        if batch_mode and _omop_workflow_batch is not None:
            return _omop_workflow_batch
        if not batch_mode and _omop_workflow_interactive is not None:
            return _omop_workflow_interactive

        # Create ONE MCP connection (shared by both agents to avoid DuckDB lock)
        # Pass Langfuse credentials to OMCP subprocess for trace propagation
        omcp_config = config["omcp"]
        
        # Build environment variables for OMCP server
        # OMCP server requires DB_TYPE and DB_PATH (for DuckDB) or DB_TYPE and PostgreSQL connection vars
        db_path = os.getenv("DB_PATH", "")
        db_type = os.getenv("DB_TYPE", "")
        
        # Auto-detect DB_TYPE from DB_PATH if not explicitly set
        if not db_type and db_path:
            if db_path.startswith("postgresql://") or db_path.startswith("postgres://"):
                db_type = "postgres"
            else:
                db_type = "duckdb"  # Default to duckdb for file paths
        elif not db_type:
            db_type = "duckdb"  # Default to duckdb if nothing is set
        
        omcp_env = {
            "DB_TYPE": db_type,
            "DB_PATH": db_path,
            "LANGFUSE_PUBLIC_KEY": os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            "LANGFUSE_SECRET_KEY": os.getenv("LANGFUSE_SECRET_KEY", ""),
            "LANGFUSE_HOST": os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        }
        
        # If using PostgreSQL, parse connection string or use individual env vars
        # OMCP server expects: DB_USERNAME, DB_PASSWORD, DB_HOST, DB_PORT, DB_DATABASE
        # Note: DB_PASSWORD can be empty (some PostgreSQL users don't have passwords)
        if db_type == "postgres" or db_type == "postgresql":
            # Check if individual env vars are set (password can be empty, but others should be set)
            has_individual_vars = all(
                os.getenv(key) is not None and os.getenv(key).lower() not in ["none"]
                for key in ["DB_USERNAME", "DB_HOST", "DB_PORT", "DB_DATABASE"]
            )
            
            if has_individual_vars:
                # Use individual environment variables
                # Password is optional (can be empty string)
                for key in ["DB_USERNAME", "DB_HOST", "DB_PORT", "DB_DATABASE"]:
                    value = os.getenv(key, "")
                    if value and value.lower() not in ["none"]:
                        omcp_env[key] = value
                # Handle password separately (can be empty)
                db_password = os.getenv("DB_PASSWORD", "")
                if db_password is not None and db_password.lower() not in ["none"]:
                    omcp_env["DB_PASSWORD"] = db_password
                else:
                    omcp_env["DB_PASSWORD"] = ""  # Empty password is valid
            elif db_path and (db_path.startswith("postgresql://") or db_path.startswith("postgres://")):
                # Try to parse connection string from DB_PATH
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(db_path)
                    # Extract values from connection string
                    omcp_env["DB_USERNAME"] = parsed.username or ""
                    # Password can be None (no password) or empty string
                    omcp_env["DB_PASSWORD"] = parsed.password if parsed.password is not None else ""
                    omcp_env["DB_HOST"] = parsed.hostname or "localhost"
                    omcp_env["DB_PORT"] = str(parsed.port) if parsed.port else "5432"
                    omcp_env["DB_DATABASE"] = parsed.path.lstrip("/") if parsed.path else ""
                except Exception as e:
                    print(f"Warning: Could not parse PostgreSQL connection string from DB_PATH: {e}")
                    print("Please set DB_USERNAME, DB_PASSWORD, DB_HOST, DB_PORT, and DB_DATABASE individually")
            else:
                # Use individual environment variables if provided
                for key in ["DB_USERNAME", "DB_HOST", "DB_PORT", "DB_DATABASE"]:
                    value = os.getenv(key, "")
                    if value and value.lower() not in ["none"]:
                        omcp_env[key] = value
                # Handle password separately (can be empty)
                db_password = os.getenv("DB_PASSWORD", "")
                if db_password is not None and db_password.lower() not in ["none"]:
                    omcp_env["DB_PASSWORD"] = db_password
                else:
                    omcp_env["DB_PASSWORD"] = ""  # Empty password is valid
        
        # For large databases (700GB+), connection initialization and queries can take longer
        # Default to 660 seconds (11 minutes) to allow for 10-minute query timeout + 1 minute buffer
        mcp_timeout = int(os.getenv("MCP_CONNECTION_TIMEOUT", "660"))
        print(f"Connecting to OMCP server (timeout: {mcp_timeout}s)...")
        print("Note: Large databases (700GB+) may take longer to initialize and execute complex queries.")
        
        # _mcp_tools = MCPTools(
        #     transport=omcp_config["transport"],
        #     command=omcp_config["command"],
        #     env=omcp_env,
        #     timeout_seconds=mcp_timeout  # Pass timeout to MCPTools
        # )

        # Manually connect MCP once
        try:
            # await _mcp_tools._connect()
            supervisor = await create_supervisor_agent(mcp_tools)                                                             
            response = await supervisor.arun(user_query) 
            print("✓ OMCP server connected successfully")
        except Exception as e:
            print(f"⚠️  MCP connection failed: {e}")
            print(f"If timeout occurred, try increasing MCP_CONNECTION_TIMEOUT (current: {mcp_timeout}s)")
            print("For very large databases, try: export MCP_CONNECTION_TIMEOUT=600  # 10 minutes")
            raise

        # Create shared database for conversation history and memory
        db = SqliteDb(db_file="db_agent.db")

        # Create compression manager for batch mode (uses same model as agents)
        # Token-based compression triggers at ~6000 tokens to save context space
        compression_manager = None
        if batch_mode:
            # Use the semantic agent config (both agents use same model provider)
            agent_config = get_agent_config("semantic")
            compression_model = create_model(agent_config)
            compression_manager = CompressionManager(
                model=compression_model,
                compress_tool_results=True,
                compress_token_limit=6000,  # Trigger compression at 6000 tokens
            )
            print("✓ Compression manager created for batch mode (token limit: 6000)")

        # Create agents with shared MCP - both query the database
        semantic_agent = create_semantic_agent(_mcp_tools)  # Queries concept table
        database_agent = create_database_agent(_mcp_tools)  # Generates & executes SQL

        # Attach compression manager to agents in batch mode
        if compression_manager is not None:
            semantic_agent.compression_manager = compression_manager
            database_agent.compression_manager = compression_manager
            print("✓ Compression manager attached to both agents")

        # Configure workflow history based on mode
        # Batch mode: disable history for performance (independent queries)
        # Interactive mode: enable history for context across conversation turns
        add_history = not batch_mode
        num_history = 0 if batch_mode else 3

        # Create linear workflow (supports structured output passing)
        workflow = Workflow(
            name="OMOP Clinical Query Workflow",
            db=db,  # Shared database enables conversation history across workflow runs
            debug_mode=True,  # Keep debug enabled for observability
            steps=[
                Step(
                    name="Semantic Extraction",
                    agent=semantic_agent,
                    description="Extract clinical concepts and map to OMOP codes",
                    add_workflow_history=add_history,
                    num_history_runs=num_history,
                ),
                Step(
                    name="SQL Generation and Execution",
                    agent=database_agent,
                    description="Generate SQL from semantic context and execute",
                    add_workflow_history=add_history,
                    num_history_runs=num_history,
                ),
            ],
        )

        # Cache the workflow based on mode
        if batch_mode:
            _omop_workflow_batch = workflow
        else:
            _omop_workflow_interactive = workflow

        return workflow


def extract_final_query_from_step(step_response) -> str:
    """
    Extract final query from a single step's response (database agent).

    Args:
        step_response: Agent's RunResponse object

    Returns:
        str: The final successful query, or None if not found
    """
    final_query = None

    try:
        # Check if step_response has messages
        messages = []
        if hasattr(step_response, 'messages') and step_response.messages:
            messages = step_response.messages
        elif hasattr(step_response, 'run_response') and hasattr(step_response.run_response, 'messages'):
            messages = step_response.run_response.messages

        # Iterate through messages to find tool calls
        for message in messages:
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tool_call in message.tool_calls:
                    # Extract tool name
                    tool_name = None
                    if hasattr(tool_call, 'function') and tool_call.function:
                        if hasattr(tool_call.function, 'name'):
                            tool_name = tool_call.function.name
                        elif hasattr(tool_call, 'tool_name'):
                            tool_name = tool_call.tool_name

                    # Check if this is a select_query call
                    if tool_name == 'select_query':
                        # Check if it was successful (no error)
                        # tool_call_error == False or missing means success
                        has_error = getattr(tool_call, 'tool_call_error', False)

                        if not has_error:
                            # Successful call - extract the query from arguments
                            args = None
                            if hasattr(tool_call, 'function') and tool_call.function:
                                if hasattr(tool_call.function, 'arguments'):
                                    try:
                                        args_raw = tool_call.function.arguments
                                        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                                    except:
                                        pass
                            elif hasattr(tool_call, 'tool_args'):
                                args = tool_call.tool_args

                            if args and 'query' in args:
                                final_query = args['query']

    except Exception as e:
        print(f"Warning: Could not extract final query from step: {e}")

    return final_query


def extract_raw_result(workflow_response) -> str:
    """
    Extract the raw CSV result from the final successful SQL query execution.

    Args:
        workflow_response: The workflow RunOutput containing execution history

    Returns:
        str: The raw CSV result from MCP server, or None if not found
    """
    raw_result = None

    try:
        # Check step_executor_runs for tool results
        if hasattr(workflow_response, 'step_executor_runs') and workflow_response.step_executor_runs:
            # Iterate through step executor runs in reverse (most recent first)
            for step_run in reversed(workflow_response.step_executor_runs):
                if hasattr(step_run, 'tools') and step_run.tools:
                    # Look through tools in reverse order (last tool call first)
                    for tool in reversed(step_run.tools):
                        # Check if this is a Select_Query tool
                        tool_name = getattr(tool, 'tool_name', None)
                        if tool_name == 'Select_Query':
                            # Check if it succeeded (isError == False)
                            result = getattr(tool, 'result', None)
                            if result:
                                is_error = False
                                # Check for isError in result
                                if hasattr(result, 'isError'):
                                    is_error = result.isError
                                elif isinstance(result, dict) and 'isError' in result:
                                    is_error = result['isError']

                                if not is_error:
                                    # Extract raw CSV content from MCP CallToolResult
                                    # Structure: result.content = [TextContent(type="text", text="<CSV>")]
                                    if hasattr(result, 'content') and result.content:
                                        content_list = result.content
                                        if isinstance(content_list, list) and len(content_list) > 0:
                                            # Get first TextContent item
                                            text_content = content_list[0]
                                            if hasattr(text_content, 'text'):
                                                raw_result = text_content.text
                                                break
                                            elif isinstance(text_content, dict) and 'text' in text_content:
                                                raw_result = text_content['text']
                                                break
                                    elif isinstance(result, dict) and 'content' in result:
                                        content_list = result['content']
                                        if isinstance(content_list, list) and len(content_list) > 0:
                                            text_content = content_list[0]
                                            if isinstance(text_content, dict) and 'text' in text_content:
                                                raw_result = text_content['text']
                                                break
                                    elif isinstance(result, str):
                                        # Fallback: result is directly a string
                                        raw_result = result
                                        break

                if raw_result:
                    break

    except Exception as e:
        import traceback
        print(f"Warning: Could not extract raw result: {e}")
        print(f"Traceback: {traceback.format_exc()}")

    return raw_result


def extract_final_query(workflow_response) -> str:
    """
    Extract the final successful query from tool execution history.
    Looks for the last select_query tool call where isError == False.

    Args:
        workflow_response: The workflow RunOutput containing execution history

    Returns:
        str: The final successful query, or None if not found
    """
    final_query = None

    try:
        # Method 1: Check step_executor_runs (matches Langfuse output structure)
        if hasattr(workflow_response, 'step_executor_runs') and workflow_response.step_executor_runs:
            # Iterate through step executor runs in reverse (most recent first)
            for step_run in reversed(workflow_response.step_executor_runs):
                if hasattr(step_run, 'tools') and step_run.tools:
                    # Look through tools in reverse order (last tool call first)
                    for tool in reversed(step_run.tools):
                        # Check if this is a Select_Query tool
                        tool_name = getattr(tool, 'tool_name', None)
                        if tool_name == 'Select_Query':
                            # Check if it succeeded (isError == False)
                            result = getattr(tool, 'result', None)
                            if result:
                                is_error = False
                                # Check for isError in result
                                if hasattr(result, 'isError'):
                                    is_error = result.isError
                                elif isinstance(result, dict) and 'isError' in result:
                                    is_error = result['isError']

                                if not is_error:
                                    # Successful query - extract it
                                    tool_args = getattr(tool, 'tool_args', None)
                                    if tool_args:
                                        if isinstance(tool_args, dict) and 'query' in tool_args:
                                            final_query = tool_args['query']
                                            break
                                        elif hasattr(tool_args, 'query'):
                                            final_query = tool_args.query
                                            break

                if final_query:
                    break

        # Method 2: Check if workflow has step_responses
        if not final_query and hasattr(workflow_response, 'step_responses') and workflow_response.step_responses:
            # Database agent is the second step (index 1)
            for step_response in reversed(workflow_response.step_responses):
                query = extract_final_query_from_step(step_response)
                if query:
                    final_query = query
                    break

        # Method 3: Check direct messages in workflow response
        if not final_query:
            final_query = extract_final_query_from_step(workflow_response)

        # Method 4: Access through run_response
        if not final_query and hasattr(workflow_response, 'run_response'):
            final_query = extract_final_query_from_step(workflow_response.run_response)

    except Exception as e:
        import traceback
        print(f"Warning: Could not extract final query: {e}")
        print(f"Traceback: {traceback.format_exc()}")

    return final_query


@observe() #Complete langfuse tracing
async def run_omop_query(user_query: str, session_id: str = None, user_id: str = None, batch_mode: bool = False) -> str:
    """
    Run OMOP clinical query via Workflow
    Initializes on first call, reuses for subsequent queries

    Args:
        user_query: The clinical query to process
        session_id: Session identifier for conversation history
        user_id: User identifier for personalized memories
        batch_mode: If True, disables workflow history for performance (independent queries)
    """
    # Inject current OpenTelemetry trace context for OMCP subprocess
    # This uses W3C Trace Context format (traceparent/tracestate)
    try:
        write_trace_context_otel(session_id=session_id)
    except Exception as e:
        # Non-critical: if trace context extraction fails, continue without it
        print(f"Warning: Could not inject OpenTelemetry trace context: {e}")

    workflow = await initialize_workflow(batch_mode=batch_mode)
    response = await workflow.arun(user_query, session_id=session_id, user_id=user_id)

    # Extract final successful query and raw CSV result from tool execution history
    try:
        final_query = extract_final_query(response)
        raw_result = extract_raw_result(response)

        # Attach as custom attributes to response for easy access in run_agent.py
        response.sql_query = final_query
        response.raw_csv_result = raw_result

        if final_query or raw_result:
            # Add to Langfuse trace output (V3 API)
            langfuse = get_client()

            # Get existing output from response
            existing_output = {}
            if hasattr(response, 'to_dict'):
                existing_output = response.to_dict()
            elif hasattr(response, '__dict__'):
                existing_output = {k: v for k, v in response.__dict__.items() if not k.startswith('_')}

            # Add SQL query and raw result to existing output
            if final_query:
                existing_output['sql_query'] = final_query
            if raw_result:
                existing_output['raw_csv_result'] = raw_result

            langfuse.update_current_trace(
                output=existing_output
            )
        else:
            print("WARNING: No SQL query or raw result found in response")

    except Exception as e:
        import traceback
        print(f"ERROR: Could not update trace with query metadata: {e}")
        print(f"ERROR traceback: {traceback.format_exc()}")

    return response


async def cleanup_workflow():
    """
    Cleanup resources (call on shutdown)
    Closes MCP connection
    """
    global _omop_workflow_interactive, _omop_workflow_batch

    # Cleanup both workflow types if they exist
    for workflow in [_omop_workflow_interactive, _omop_workflow_batch]:
        if workflow is not None and hasattr(workflow, 'steps'):
            for step in workflow.steps:
                if hasattr(step.agent, 'tools'):
                    for tool in step.agent.tools:
                        if hasattr(tool, 'close'):
                            await tool.close()


    langfuse = Langfuse()
    langfuse.flush()