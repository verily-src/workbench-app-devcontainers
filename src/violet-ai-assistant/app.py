from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import subprocess
import os
import logging
import tempfile

app = Flask(__name__)
app.config['STRICT_SLASHES'] = False
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store chat history per project
chat_histories = {}

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

def set_gemini_project(project_id: str):
    """Configure Gemini CLI to use the specified GCP project."""
    try:
        result = subprocess.run(
            ['gemini', 'config', 'set', 'project', project_id],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            logger.error(f"Failed to set Gemini project: {result.stderr}")
            return False
        logger.info(f"Set Gemini project to: {project_id}")
        return True
    except Exception as e:
        logger.error(f"Error setting Gemini project: {str(e)}")
        return False

def chat_with_gemini(message: str, project_id: str, history: list) -> str:
    """Send a message to Gemini CLI and get response."""
    # Set the project context
    if not set_gemini_project(project_id):
        raise Exception("Failed to configure Gemini with project")

    # Create a temporary file for the conversation history
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        history_file = f.name
        # Write history in Gemini CLI format
        conversation = {
            "messages": []
        }
        for msg in history:
            conversation["messages"].append({
                "role": msg["role"],
                "content": msg["content"]
            })
        json.dump(conversation, f)

    try:
        # Build Gemini CLI command
        cmd = ['gemini', 'chat']

        # Add history file if we have previous messages
        if history:
            cmd.extend(['--history', history_file])

        # Add the message
        cmd.append(message)

        # Run Gemini CLI
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, 'GOOGLE_CLOUD_PROJECT': project_id}
        )

        if result.returncode != 0:
            logger.error(f"Gemini CLI error: {result.stderr}")
            raise Exception(f"Gemini CLI failed: {result.stderr}")

        # Parse the response
        response_text = result.stdout.strip()

        # Clean up any CLI formatting
        if response_text.startswith('Gemini:'):
            response_text = response_text[7:].strip()

        return response_text

    finally:
        # Clean up temporary file
        try:
            os.unlink(history_file)
        except:
            pass

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

        # Get response from Gemini CLI
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
