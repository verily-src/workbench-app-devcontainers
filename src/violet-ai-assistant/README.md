# Violet AI Assistant

Meet Violet, your AI-powered assistant for Verily Workbench. Violet uses Vertex AI's Gemini model to help you with data analysis, bioinformatics workflows, cloud resource management, and more.

## Features

- **Gemini-Powered**: Uses Vertex AI's Gemini 1.5 Pro model for intelligent assistance
- **Multi-Project Support**: Select from any GCP project available in your Workbench workspace
- **Workbench Integration**: Automatically detects and lists your Workbench GCP projects
- **Chat History**: Maintains conversation context per project
- **Material-UI Design**: Clean interface matching Workbench's design aesthetic

## What Violet Can Help With

- Understanding your Workbench environment and resources
- Data analysis and bioinformatics workflows
- Python, R, and SQL queries
- Cloud resource management (GCP, BigQuery, Cloud Storage)
- Best practices for scientific computing
- General coding and troubleshooting

## Quick Start

### Deploy to Workbench

1. In Workbench UI, create a new Custom Application
2. Repository: This repo URL
3. Branch: Your branch name
4. Folder: `src/violet-ai-assistant`
5. Wait for the app to build and start

### Access the App

Once running, access Violet at:
```
https://workbench.verily.com/app/[YOUR-APP-ID]/proxy/8080/
```

## Local Testing

```bash
# Create the app network
docker network create app-network

# Build and run
cd src/violet-ai-assistant
docker compose up --build

# Access at http://localhost:8080
```

## Architecture

- **Backend**: Flask app with Vertex AI Python SDK
- **Frontend**: Material-UI styled single-page application
- **Integration**: Uses Workbench CLI (`wb`) to list GCP projects
- **AI Model**: Gemini 1.5 Pro via Vertex AI

## Configuration

### Environment Variables

- `GOOGLE_CLOUD_PROJECT`: Default GCP project (automatically set by Workbench)

### GCP Requirements

- The app must have access to Vertex AI API in the selected GCP projects
- Workbench authentication is automatically configured

## Usage Tips

1. **Select a Project**: Choose your GCP project from the dropdown at the top
2. **Ask Questions**: Type your question in the input box and press Enter
3. **Code Blocks**: Violet will format code examples with syntax highlighting
4. **Clear Chat**: Use the "Clear Chat" button to start a new conversation
5. **Keyboard Shortcuts**:
   - Enter to send message
   - Shift+Enter for new line

## API Endpoints

- `GET /`: Main chat interface
- `GET /api/projects`: List available GCP projects
- `POST /api/chat`: Send a message to Violet
- `POST /api/clear`: Clear chat history for a project
- `GET /api/health`: Health check

## Design Philosophy

Violet's interface is designed to match Workbench's aesthetic:
- Material-UI components with Enterprise Light Theme
- Purple accent color (#7B1FA2) for branding
- Clean, professional layout
- Responsive design
- Accessible with keyboard navigation

## Future Enhancements

Potential features for integration into Workbench:
- Bottom-right popup chat widget
- System tray integration
- Quick actions for common tasks
- Resource-aware context (current workspace, data tables, etc.)
- Integration with Workbench MCP server for enhanced capabilities

## Troubleshooting

### No projects showing
- Ensure you have GCP projects configured in Workbench
- Check that `wb` CLI is available and authenticated

### API errors
- Verify Vertex AI API is enabled in your GCP project
- Check that the app has proper permissions

### Chat not responding
- Check server logs: `docker logs application-server`
- Verify the selected project has Vertex AI API enabled
- Ensure you're using the correct proxy URL format

## Technical Details

### Dependencies
- Flask 3.0.0 - Web framework
- Flask-CORS 4.0.0 - CORS support
- google-cloud-aiplatform 1.38.0 - Vertex AI SDK

### Workbench Features Used
- `workbench-tools` - Provides `wb` CLI for project listing and authentication

## Support

For issues or questions:
- Check the Workbench documentation
- Review server logs for error messages
- Ensure all GCP APIs are enabled and permissions are configured

---

Built with 💜 for Verily Workbench
