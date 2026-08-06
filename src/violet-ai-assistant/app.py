from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import subprocess
import os
import logging
import requests
import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    Content,
    Part,
    Tool,
    FunctionDeclaration,
    GenerationConfig
)

app = Flask(__name__)
app.config['STRICT_SLASHES'] = False
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Workbench and Vertex AI configuration
WORKBENCH_API_BASE = "https://workbench.verily.com/api/wsm"
VERTEX_AI_LOCATION = "us-central1"
GEMINI_MODEL = "gemini-2.5-flash"

# Store chat history per project
chat_histories = {}

# Define MCP tools as function declarations

# Workspace functions
wb_status_func = FunctionDeclaration(
    name="wb_status",
    description="Get workspace and server status",
    parameters={"type": "object", "properties": {}}
)

wb_workspace_list_func = FunctionDeclaration(
    name="wb_workspace_list",
    description="List all workspaces",
    parameters={
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": ["json", "text"]}
        }
    }
)

workspace_create_func = FunctionDeclaration(
    name="workspace_create",
    description="Create a new workspace",
    parameters={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "User-facing workspace ID"},
            "podId": {"type": "string", "description": "Pod ID"},
            "name": {"type": "string", "description": "Display name"},
            "description": {"type": "string", "description": "Description"}
        },
        "required": ["id", "podId"]
    }
)

workspace_get_func = FunctionDeclaration(
    name="workspace_get",
    description="Get workspace details by ID",
    parameters={
        "type": "object",
        "properties": {
            "workspaceId": {"type": "string", "description": "User-facing workspace ID"}
        },
        "required": ["workspaceId"]
    }
)

workspace_list_all_func = FunctionDeclaration(
    name="workspace_list_all",
    description="List all workspaces with optional property filters",
    parameters={
        "type": "object",
        "properties": {
            "properties": {"type": "object"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"}
        }
    }
)

workspace_list_resources_func = FunctionDeclaration(
    name="workspace_list_resources",
    description="List all resources in a workspace",
    parameters={
        "type": "object",
        "properties": {
            "workspaceId": {"type": "string", "description": "User-facing workspace ID"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"}
        },
        "required": ["workspaceId"]
    }
)

workspace_list_users_func = FunctionDeclaration(
    name="workspace_list_users",
    description="List all users with access to a workspace",
    parameters={
        "type": "object",
        "properties": {
            "workspaceId": {"type": "string", "description": "User-facing workspace ID"}
        },
        "required": ["workspaceId"]
    }
)

# Resource functions
resource_create_bucket_func = FunctionDeclaration(
    name="resource_create_bucket",
    description="Create a cloud storage bucket",
    parameters={
        "type": "object",
        "properties": {
            "resourceId": {"type": "string", "description": "Resource ID"},
            "bucketName": {"type": "string", "description": "Bucket name"},
            "description": {"type": "string", "description": "Description"}
        },
        "required": ["resourceId", "bucketName"]
    }
)

resource_create_bq_dataset_func = FunctionDeclaration(
    name="resource_create_bq_dataset",
    description="Create a BigQuery dataset",
    parameters={
        "type": "object",
        "properties": {
            "resourceId": {"type": "string", "description": "Resource ID"},
            "datasetId": {"type": "string", "description": "Dataset ID"},
            "description": {"type": "string", "description": "Description"}
        },
        "required": ["resourceId", "datasetId"]
    }
)

resource_check_access_func = FunctionDeclaration(
    name="resource_check_access",
    description="Check if user has access to a resource",
    parameters={
        "type": "object",
        "properties": {
            "resourceId": {"type": "string", "description": "Resource ID"}
        },
        "required": ["resourceId"]
    }
)

resource_list_tree_func = FunctionDeclaration(
    name="resource_list_tree",
    description="List resources in tree view",
    parameters={"type": "object", "properties": {}}
)

# Folder functions
folder_create_func = FunctionDeclaration(
    name="folder_create",
    description="Create a folder to organize resources",
    parameters={
        "type": "object",
        "properties": {
            "folderId": {"type": "string", "description": "Folder ID"},
            "displayName": {"type": "string", "description": "Display name"},
            "description": {"type": "string", "description": "Description"}
        },
        "required": ["folderId", "displayName"]
    }
)

folder_list_tree_func = FunctionDeclaration(
    name="folder_list_tree",
    description="Show folder hierarchy as a tree",
    parameters={"type": "object", "properties": {}}
)

# Data collection functions
workspace_list_data_collections_func = FunctionDeclaration(
    name="workspace_list_data_collections",
    description="List data collections in current workspace",
    parameters={"type": "object", "properties": {}}
)

platform_list_data_collections_func = FunctionDeclaration(
    name="platform_list_data_collections",
    description="Search all data collections accessible across Workbench",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword"},
            "limit": {"type": "integer", "description": "Max results"}
        }
    }
)

# App functions
app_create_func = FunctionDeclaration(
    name="app_create",
    description="Create an application (JupyterLab, RStudio, VSCode)",
    parameters={
        "type": "object",
        "properties": {
            "appId": {"type": "string", "description": "Application ID"},
            "appConfig": {"type": "string", "description": "Config: jupyter-lab, r-analysis, visual-studio-code"},
            "machineType": {"type": "string", "description": "Machine type"},
            "description": {"type": "string", "description": "Description"}
        },
        "required": ["appId", "appConfig"]
    }
)

app_list_func = FunctionDeclaration(
    name="app_list",
    description="List all applications in workspace",
    parameters={"type": "object", "properties": {}}
)

app_start_func = FunctionDeclaration(
    name="app_start",
    description="Start a stopped application",
    parameters={
        "type": "object",
        "properties": {
            "appId": {"type": "string", "description": "Application ID"}
        },
        "required": ["appId"]
    }
)

app_stop_func = FunctionDeclaration(
    name="app_stop",
    description="Stop a running application",
    parameters={
        "type": "object",
        "properties": {
            "appId": {"type": "string", "description": "Application ID"}
        },
        "required": ["appId"]
    }
)

app_get_url_func = FunctionDeclaration(
    name="app_get_url",
    description="Get the launch URL for an application",
    parameters={
        "type": "object",
        "properties": {
            "appId": {"type": "string", "description": "Application ID"}
        },
        "required": ["appId"]
    }
)

# Underlay (data model) functions
underlay_list_func = FunctionDeclaration(
    name="underlay_list",
    description="List all available data models (underlays)",
    parameters={"type": "object", "properties": {}}
)

underlay_get_schema_func = FunctionDeclaration(
    name="underlay_get_schema",
    description="Get complete underlay schema with entities and attributes",
    parameters={
        "type": "object",
        "properties": {
            "underlayName": {"type": "string", "description": "Underlay name"}
        },
        "required": ["underlayName"]
    }
)

underlay_list_entities_func = FunctionDeclaration(
    name="underlay_list_entities",
    description="List all entities in an underlay (e.g., Person, Condition)",
    parameters={
        "type": "object",
        "properties": {
            "underlayName": {"type": "string", "description": "Underlay name"}
        },
        "required": ["underlayName"]
    }
)

underlay_get_entity_func = FunctionDeclaration(
    name="underlay_get_entity",
    description="Get entity details including attributes and relationships",
    parameters={
        "type": "object",
        "properties": {
            "underlayName": {"type": "string", "description": "Underlay name"},
            "entityName": {"type": "string", "description": "Entity name"}
        },
        "required": ["underlayName", "entityName"]
    }
)

# CLI executor functions
bq_execute_func = FunctionDeclaration(
    name="bq_execute",
    description="Execute BigQuery command in workspace context",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "BigQuery command (without 'bq' prefix)"}
        },
        "required": ["command"]
    }
)

# Create tool with MCP function declarations
mcp_tool = Tool(function_declarations=[
    wb_status_func,
    wb_workspace_list_func,
    workspace_create_func,
    workspace_get_func,
    workspace_list_all_func,
    workspace_list_resources_func,
    workspace_list_users_func,
    resource_create_bucket_func,
    resource_create_bq_dataset_func,
    resource_check_access_func,
    resource_list_tree_func,
    folder_create_func,
    folder_list_tree_func,
    workspace_list_data_collections_func,
    platform_list_data_collections_func,
    app_create_func,
    app_list_func,
    app_start_func,
    app_stop_func,
    app_get_url_func,
    underlay_list_func,
    underlay_get_schema_func,
    underlay_list_entities_func,
    underlay_get_entity_func,
    bq_execute_func,
])

def get_auth_token():
    """Get OAuth2 bearer token from gcloud."""
    try:
        result = subprocess.run(
            ['sudo', '-u', 'app', 'bash', '-l', '-c', 'gcloud auth print-access-token'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Error getting auth token: {str(e)}")
        return None

def get_workbench_projects():
    """Get list of ALL GCP workspaces from Workbench API with pagination."""
    try:
        token = get_auth_token()
        if not token:
            return []

        url = f"{WORKBENCH_API_BASE}/api/workspaces/v1"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        all_workspaces = []
        offset = 0
        limit = 100  # Fetch 100 at a time

        # Paginate through all workspaces
        while True:
            params = {'offset': offset, 'limit': limit}
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            workspaces = data.get('workspaces', [])

            if not workspaces:
                break  # No more workspaces

            all_workspaces.extend(workspaces)

            # If we got fewer than limit, we're done
            if len(workspaces) < limit:
                break

            offset += limit

        logger.info(f"Fetched {len(all_workspaces)} total workspaces")

        # Filter to only GCP workspaces and extract project info
        projects = []
        for ws in all_workspaces:
            gcp_context = ws.get('gcpContext', {})
            project_id = gcp_context.get('projectId')

            if project_id:
                projects.append({
                    'id': ws.get('id', ''),
                    'workspaceId': ws.get('userFacingId', ''),
                    'name': ws.get('displayName', '') or ws.get('userFacingId', ''),
                    'projectId': project_id
                })

        logger.info(f"Found {len(projects)} GCP workspaces")
        return projects

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to list workspaces: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error getting workspaces: {str(e)}")
        return []

def get_default_project():
    """Get the default GCP project from environment."""
    return os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GOOGLE_PROJECT')

def execute_mcp_function(function_name: str, args: dict) -> dict:
    """Execute an MCP function by calling the wb-mcp-server via HTTP."""
    try:
        mcp_url = "http://127.0.0.1:9242"

        # Map function names to MCP tool names
        tool_map = {
            "wb_status": "wb_status",
            "wb_workspace_list": "wb_workspace_list",
            "workspace_create": "workspace_create",
            "workspace_get": "workspace_get",
            "workspace_list_all": "workspace_list_all",
            "workspace_list_resources": "workspace_list_resources",
            "workspace_list_users": "workspace_list_users",
            "resource_create_bucket": "resource_create_bucket",
            "resource_create_bq_dataset": "resource_create_bq_dataset",
            "resource_check_access": "resource_check_access",
            "resource_list_tree": "resource_list_tree",
            "folder_create": "folder_create",
            "folder_list_tree": "folder_list_tree",
            "workspace_list_data_collections": "workspace_list_data_collections",
            "platform_list_data_collections": "platform_list_data_collections",
            "app_create": "app_create",
            "app_list": "app_list",
            "app_start": "app_start",
            "app_stop": "app_stop",
            "app_get_url": "app_get_url",
            "underlay_list": "underlay_list",
            "underlay_get_schema": "underlay_get_schema",
            "underlay_list_entities": "underlay_list_entities",
            "underlay_get_entity": "underlay_get_entity",
            "bq_execute": "bq_execute",
        }

        tool_name = tool_map.get(function_name)
        if not tool_name:
            return {"error": f"Unknown function: {function_name}"}

        # Call MCP server
        payload = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args
            }
        }

        response = requests.post(mcp_url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        return result

    except Exception as e:
        logger.error(f"Error executing MCP function {function_name}: {str(e)}")
        return {"error": str(e)}

def chat_with_gemini(message: str, project_id: str, history: list) -> tuple[str, list]:
    """Send a message to Gemini via Vertex AI SDK with function calling."""
    try:
        # Initialize Vertex AI for this project
        logger.info(f"Initializing Vertex AI with project={project_id}, location={VERTEX_AI_LOCATION}")
        vertexai.init(project=project_id, location=VERTEX_AI_LOCATION)

        # Create model with MCP tools
        model = GenerativeModel(
            GEMINI_MODEL,
            tools=[mcp_tool]
        )

        # Convert history to Vertex AI format
        contents = []
        system_instruction = None

        for msg in history:
            role = msg['role']
            if role == 'system':
                system_instruction = msg['content']
            elif role == 'user':
                contents.append(Content(role='user', parts=[Part.from_text(msg['content'])]))
            elif role == 'assistant':
                contents.append(Content(role='model', parts=[Part.from_text(msg['content'])]))

        # Add the new user message
        contents.append(Content(role='user', parts=[Part.from_text(message)]))

        # Start chat session with system instruction if exists
        if system_instruction:
            chat = model.start_chat()
            # System instructions need to be in generation config for SDK
            generation_config = GenerationConfig(
                temperature=0.7,
                max_output_tokens=2048
            )
        else:
            chat = model.start_chat()
            generation_config = GenerationConfig(
                temperature=0.7,
                max_output_tokens=2048
            )

        # Send message and handle function calling loop
        max_iterations = 5
        iteration = 0
        accumulated_responses = []

        while iteration < max_iterations:
            iteration += 1

            # Get response
            response = chat.send_message(contents[-1].parts, generation_config=generation_config)

            # Check if there are function calls
            if response.candidates[0].content.parts[0].function_call:
                function_call = response.candidates[0].content.parts[0].function_call
                function_name = function_call.name
                function_args = dict(function_call.args)

                logger.info(f"Function call: {function_name}({function_args})")

                # Execute the function
                function_result = execute_mcp_function(function_name, function_args)

                # Add function response to chat
                function_response_part = Part.from_function_response(
                    name=function_name,
                    response={"result": function_result}
                )

                # Continue the conversation with function result
                contents.append(Content(role='function', parts=[function_response_part]))

            else:
                # No function call, we have the final text response
                response_text = response.text
                accumulated_responses.append(response_text)
                break

        final_response = "\n".join(accumulated_responses) if accumulated_responses else "I apologize, but I couldn't complete that request."

        return final_response, contents

    except Exception as e:
        logger.error(f"Error calling Vertex AI: {str(e)}")
        raise Exception(f"Vertex AI error: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/projects')
def get_projects():
    """Get available GCP workspaces."""
    try:
        projects = get_workbench_projects()
        default_project = get_default_project()

        return jsonify({
            'projects': projects,
            'default': default_project
        })
    except Exception as e:
        logger.error(f"Error in /api/projects: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """Send a message to Violet and get a response."""
    try:
        data = request.json
        message = data.get('message', '').strip()
        project_id = data.get('projectId', '')

        if not message:
            return jsonify({'error': 'Message is required'}), 400

        if not project_id:
            return jsonify({'error': 'Project ID is required'}), 400

        logger.info(f"Chat request for project: {project_id}")

        # Get or create chat history for this project
        if project_id not in chat_histories:
            chat_histories[project_id] = []

        # Add system instruction as first message if history is empty
        if not chat_histories[project_id]:
            system_message = """You are Violet, a helpful AI assistant for Verily Workbench users.

You help users with:
- Understanding their Workbench environment and resources
- Data analysis and bioinformatics workflows
- Exploring data collections and creating cohorts
- Python, R, and SQL queries
- Cloud resource management (GCP, BigQuery, Cloud Storage)
- Managing workspaces, applications, and compute resources
- Best practices for scientific computing

You have access to MCP tools including:

WORKSPACE MANAGEMENT:
- wb_status: Get workspace and server status
- workspace_get: Get workspace details
- workspace_list_all: List all workspaces
- workspace_list_resources: List resources in a workspace
- workspace_list_users: See who has access to a workspace
- workspace_create: Create new workspaces

RESOURCES:
- resource_create_bucket: Create cloud storage buckets
- resource_create_bq_dataset: Create BigQuery datasets
- resource_check_access: Check resource permissions
- resource_list_tree: View resources in tree hierarchy
- folder_create: Create folders to organize resources
- folder_list_tree: View folder structure

DATA COLLECTIONS:
- platform_list_data_collections: Search all available data collections
- workspace_list_data_collections: List collections in current workspace

APPLICATIONS:
- app_list: List all applications (JupyterLab, RStudio, etc.)
- app_create: Create new applications
- app_start/app_stop: Start or stop applications
- app_get_url: Get application launch URLs

DATA EXPLORER:
- underlay_list: List available data models
- underlay_get_schema: Get complete schema
- underlay_list_entities: List entities (Person, Condition, etc.)
- underlay_get_entity: Get entity details

QUERIES:
- bq_execute: Execute BigQuery commands

Be concise, friendly, and focus on practical solutions. When providing code examples,
make them ready to run in a Workbench environment."""

            chat_histories[project_id].append({
                'role': 'system',
                'content': system_message
            })

        # Get response from Vertex AI with function calling
        response_text, updated_contents = chat_with_gemini(
            message,
            project_id,
            chat_histories[project_id]
        )

        # Update history
        chat_histories[project_id].append({
            'role': 'user',
            'content': message
        })
        chat_histories[project_id].append({
            'role': 'assistant',
            'content': response_text
        })

        return jsonify({
            'response': response_text,
            'history': [
                msg for msg in chat_histories[project_id]
                if msg['role'] != 'system'  # Don't send system message to frontend
            ]
        })

    except Exception as e:
        logger.error(f"Error in /api/chat: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear', methods=['POST'])
def clear_chat():
    """Clear the chat history for a project."""
    try:
        data = request.json
        project_id = data.get('projectId', '')

        if project_id in chat_histories:
            del chat_histories[project_id]
            logger.info(f"Cleared chat history for {project_id}")

        return jsonify({'status': 'cleared'})
    except Exception as e:
        logger.error(f"Error in /api/clear: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
