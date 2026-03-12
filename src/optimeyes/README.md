# OPTIMEyes (optimeyes)

Ophthalmology image annotation application with Flask, CouchDB, and MONAI Label support for medical imaging workflows.

## Overview

OPTIMEyes is a web-based annotation platform designed for ophthalmological image analysis. This devcontainer provides a complete environment for deploying and developing the OPTIMEyes application within Workbench, integrating Flask web framework, CouchDB database, and support for MONAI Label medical imaging segmentation.

## Features

### Application Stack
- **Flask Web Server**: Lightweight Python web framework for serving the annotation interface
- **CouchDB Database**: JSON document store for persisting annotation data and metadata
- **Python 3.10**: Modern Python environment with comprehensive scientific computing libraries
- **MONAI Label Ready**: Environment prepared for medical imaging segmentation workflows

### Python Libraries
- **Web Framework**: Flask, Flask-Login, Flask-CORS, Werkzeug
- **Database**: CouchDB client for document storage
- **Image Processing**: Pillow, scikit-image, pycocotools
- **Data Analysis**: pandas for data manipulation
- **Development**: pytest for testing, mypy for type checking
- **Deployment**: gunicorn WSGI server, mkdocs for documentation

### Cloud Integration
- AWS CLI for Amazon Web Services
- Google Cloud CLI for GCP
- Workbench tools for data management

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |
| db_user | CouchDB admin username | string | admin |
| db_password | CouchDB admin password | string | password |
| secret_key | Flask secret key for sessions | string | dev-secret-key-change-in-production |

**Security Note**: Always change `db_password` and `secret_key` before deploying to production environments.

## Architecture

The devcontainer runs two primary services:

1. **Application Server** (Port 80/5000): Flask application serving the annotation interface
2. **CouchDB Server** (Port 5984): Document database for storing annotations

## Getting Started

### Initial Setup

After launching the devcontainer:

1. **Access the Application**: Navigate to the forwarded port (typically port 80)
2. **Database Access**: CouchDB admin interface available at port 5984
3. **Workspace**: Your files are mounted at `/workspace`

### Running the Application

The Flask application can be started with:

```bash
cd /workspace
# Set up your Flask application
export FLASK_APP=OPTIMEyes
flask run --host=0.0.0.0 --port=80
```

Or use gunicorn for production:

```bash
gunicorn -w 4 -b 0.0.0.0:80 OPTIMEyes:app
```

### Database Configuration

CouchDB is automatically configured with the credentials provided in template options:
- Default URL: `http://couchdb:5984`
- Database name: `image_comparator`

### Directory Structure

```
/workspace/
├── flask_server/       # Flask application code
├── data/              # Image data storage
└── config/            # User configuration
```

## Development

### Adding Dependencies

To add Python packages, update `/workspace/requirements.txt` and rebuild:

```bash
pip install -r requirements.txt
```

### Testing

Run the test suite:

```bash
pytest
```

### Type Checking

Validate type annotations:

```bash
mypy flask_server/
```

## File Support

This environment can work with:
- Python scripts (.py)
- Jupyter notebooks (.ipynb)
- Web files (.html, .css, .js)
- Medical imaging formats (.nii, .dcm)
- Data files (.json, .csv, .tsv)
- Documentation (.md)

## Integration with MONAI Label

The environment is prepared for MONAI Label integration. To add MONAI Label:

1. Install MONAI Label: `pip install monailabel`
2. Configure MONAI Label apps in your workspace
3. Update docker-compose.yaml to include MONAI Label service if needed

## Use Cases

This template is designed for:
- Ophthalmological image annotation projects
- Medical imaging research workflows
- Collaborative annotation tasks
- Development of custom annotation interfaces
- Integration with AI/ML segmentation models

## Related Resources

- Original Project: [QTIM-Lab/OPTIMEyes](https://github.com/QTIM-Lab/OPTIMEyes)
- MONAI Label: [Project MONAI](https://monai.io/)
- CouchDB Documentation: [CouchDB](https://couchdb.apache.org/)
- Flask Documentation: [Flask](https://flask.palletsprojects.com/)

## Security Considerations

- Change default passwords before production deployment
- Use strong secret keys for Flask session management
- Consider SSL/TLS for production environments
- Implement proper authentication and authorization
- Follow HIPAA guidelines if handling protected health information

---

_Note: This template adapts the OPTIMEyes application for Workbench deployment. Refer to the original OPTIMEyes repository for application-specific documentation and usage guides._
