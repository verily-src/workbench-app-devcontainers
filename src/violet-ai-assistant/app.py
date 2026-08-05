from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import subprocess
import os
import logging
import requests

app = Flask(__name__)
app.config['STRICT_SLASHES'] = False
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Workbench API configuration
WORKBENCH_API_BASE = "https://workbench.verily.com/api/wsm"

# Gemini CLI environment
GEMINI_ENV = {
    'GOOGLE_GENAI_USE_VERTEXAI': 'true',
    'GOOGLE_CLOUD_LOCATION': 'us-central1',
    'GEMINI_CLI_TRUST_WORKSPACE': 'true'
}

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

def chat_with_gemini(message: str, project_id: str) -> str:
    """Send a message to Gemini CLI and get response with MCP tool access."""
    try:
        # Build environment with Gemini config
        env = {**os.environ, **GEMINI_ENV, 'GOOGLE_CLOUD_PROJECT': project_id}

        # Use --prompt for non-interactive mode
        cmd = ['sudo', '-u', 'app', 'bash', '-l', '-c', f'gemini --prompt "{message}"']

        # Run Gemini CLI
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd='/workspace'
        )

        if result.returncode != 0:
            logger.error(f"Gemini CLI error: {result.stderr}")
            raise Exception(f"Gemini CLI failed: {result.stderr}")

        # Get the response
        response_text = result.stdout.strip()

        # Clean up any CLI formatting
        if response_text.startswith('Gemini:'):
            response_text = response_text[7:].strip()

        return response_text

    except subprocess.TimeoutExpired:
        raise Exception("Gemini CLI timed out")
    except Exception as e:
        logger.error(f"Error calling Gemini CLI: {str(e)}")
        raise

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

        # Get response from Gemini CLI (which has MCP tool access)
        response_text = chat_with_gemini(message, project_id)

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
            'history': chat_histories[project_id]
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
