from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import vertexai
from vertexai.generative_models import GenerativeModel, ChatSession
import json
import subprocess
import os
import logging

app = Flask(__name__)
app.config['STRICT_SLASHES'] = False
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store chat sessions per project
chat_sessions = {}

def get_workbench_projects():
    """Get list of GCP projects from Workbench CLI."""
    try:
        result = subprocess.run(
            ['wb', 'resource', 'list', '--type=GCP_PROJECT', '--format=json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        projects = json.loads(result.stdout)
        return [
            {
                'id': p.get('resourceId', ''),
                'name': p.get('name', ''),
                'projectId': p.get('projectId', '')
            }
            for p in projects if p.get('projectId')
        ]
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to list projects: {e.stderr}")
        return []
    except Exception as e:
        logger.error(f"Error getting projects: {str(e)}")
        return []

def get_default_project():
    """Get the default GCP project from environment or gcloud config."""
    # Try environment variable first (set by Workbench)
    project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    if project:
        return project

    # Try gcloud config
    try:
        result = subprocess.run(
            ['gcloud', 'config', 'get-value', 'project'],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        project = result.stdout.strip()
        if project and project != '(unset)':
            return project
    except Exception as e:
        logger.error(f"Error getting default project: {str(e)}")

    return None

def get_chat_session(project_id: str, location: str = "us-central1") -> ChatSession:
    """Get or create a chat session for the given project."""
    session_key = f"{project_id}:{location}"

    if session_key not in chat_sessions:
        try:
            # Initialize Vertex AI with the project
            vertexai.init(project=project_id, location=location)

            # Create a new chat session with Gemini
            model = GenerativeModel("gemini-1.5-pro")

            # System instruction for Violet
            system_instruction = """You are Violet, a helpful AI assistant for Verily Workbench users.

You help users with:
- Understanding their Workbench environment and resources
- Data analysis and bioinformatics workflows
- Python, R, and SQL queries
- Cloud resource management (GCP, BigQuery, Cloud Storage)
- Best practices for scientific computing

Be concise, friendly, and focus on practical solutions. When providing code examples,
make them ready to run in a Workbench environment."""

            chat = model.start_chat(response_validation=False)
            chat_sessions[session_key] = {
                'chat': chat,
                'system_instruction': system_instruction,
                'history': []
            }
            logger.info(f"Created new chat session for project {project_id}")
        except Exception as e:
            logger.error(f"Error creating chat session: {str(e)}")
            raise

    return chat_sessions[session_key]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/projects')
def get_projects():
    """Get available GCP projects."""
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
        location = data.get('location', 'us-central1')

        if not message:
            return jsonify({'error': 'Message is required'}), 400

        if not project_id:
            return jsonify({'error': 'Project ID is required'}), 400

        # Get or create chat session
        session_data = get_chat_session(project_id, location)
        chat = session_data['chat']

        # Send message and get response
        response = chat.send_message(message)
        response_text = response.text

        # Store in history
        session_data['history'].append({
            'role': 'user',
            'content': message
        })
        session_data['history'].append({
            'role': 'assistant',
            'content': response_text
        })

        return jsonify({
            'response': response_text,
            'history': session_data['history']
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
        location = data.get('location', 'us-central1')

        session_key = f"{project_id}:{location}"
        if session_key in chat_sessions:
            del chat_sessions[session_key]
            logger.info(f"Cleared chat session for {session_key}")

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
