from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import subprocess
import os
import logging
import requests
import vertexai
from vertexai.generative_models import GenerativeModel, Content, Part

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
    """Get list of GCP workspaces from Workbench API."""
    try:
        token = get_auth_token()
        if not token:
            return []

        url = f"{WORKBENCH_API_BASE}/api/workspaces/v1"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        workspaces = data.get('workspaces', [])

        # Filter to only GCP workspaces and extract project info
        projects = []
        for ws in workspaces:
            gcp_context = ws.get('gcpContext', {})
            project_id = gcp_context.get('projectId')

            if project_id:
                projects.append({
                    'id': ws.get('id', ''),
                    'workspaceId': ws.get('userFacingId', ''),
                    'name': ws.get('displayName', '') or ws.get('userFacingId', ''),
                    'projectId': project_id
                })

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

def chat_with_gemini(message: str, project_id: str, history: list) -> str:
    """Send a message to Gemini via Vertex AI SDK and get response."""
    try:
        # Initialize Vertex AI for this project
        vertexai.init(project=project_id, location=VERTEX_AI_LOCATION)

        # Create model
        model = GenerativeModel(GEMINI_MODEL)

        # Convert history to Vertex AI format
        contents = []
        for msg in history:
            role = msg['role']
            if role == 'system':
                # System messages can be prepended to first user message
                continue
            elif role == 'user':
                contents.append(Content(role='user', parts=[Part.from_text(msg['content'])]))
            elif role == 'assistant':
                contents.append(Content(role='model', parts=[Part.from_text(msg['content'])]))

        # Add the new user message
        contents.append(Content(role='user', parts=[Part.from_text(message)]))

        # Get system message if exists
        system_instruction = None
        for msg in history:
            if msg['role'] == 'system':
                system_instruction = msg['content']
                break

        # Generate response
        if system_instruction:
            model_with_system = GenerativeModel(
                GEMINI_MODEL,
                system_instruction=system_instruction
            )
            response = model_with_system.generate_content(contents)
        else:
            response = model.generate_content(contents)

        return response.text

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
- Best practices for scientific computing

You have access to Workbench MCP tools that let you:
- List available data collections
- Explore data schemas and entities
- Create cohorts with complex filters
- Manage workspace resources

Be concise, friendly, and focus on practical solutions. When providing code examples,
make them ready to run in a Workbench environment."""

            chat_histories[project_id].append({
                'role': 'system',
                'content': system_message
            })

        # Get response from Vertex AI
        response_text = chat_with_gemini(
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
