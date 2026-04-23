"""
Simple Flask server to serve the built React SPA.
Handles routing for Workbench proxy at /app/UUID/proxy/8080/dashboard/
"""
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
import os

app = Flask(__name__, static_folder='dist')
CORS(app)

@app.route('/dashboard/health')
def health():
    return jsonify({"status": "ok", "app": "stat-expl"})

@app.route('/dashboard/docs/<path:path>')
def serve_docs(path):
    """Serve schema.json and other docs"""
    return send_from_directory('public/docs', path)

@app.route('/dashboard/')
@app.route('/dashboard/<path:path>')
def serve_app(path=''):
    """
    Serve the React SPA.
    All routes go to index.html for client-side routing.
    Assets like JS/CSS are served from their actual paths.
    """
    # If path exists in dist (e.g., assets/), serve it directly
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)

    # Otherwise serve index.html for client-side routing
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    # CRITICAL: host='0.0.0.0' required for Workbench proxy access
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
