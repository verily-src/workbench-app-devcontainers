import re


SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$|^[0-9]{6,20}$")
_LOCATION = re.compile(r"^(?:global|[a-z]+-[a-z0-9]+)$")


class VertexAuthUnavailable(RuntimeError):
    pass


def endpoint(project: str, location: str) -> str:
    project = (project or "").strip()
    location = (location or "").strip()
    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("Invalid Google Cloud project ID.")
    if not _LOCATION.fullmatch(location):
        raise ValueError("Invalid Vertex AI location.")
    host = ("aiplatform.googleapis.com" if location == "global"
            else f"{location}-aiplatform.googleapis.com")
    return (f"https://{host}/v1beta1/projects/{project}/locations/"
            f"{location}/endpoints/openapi")


def new_client(project: str, location: str):
    try:
        from google.auth import default
        from google.auth.transport.requests import Request
        from openai import OpenAI
    except ImportError as exc:
        raise VertexAuthUnavailable(
            "Vertex AI needs google-auth and the OpenAI Python client.") from exc
    try:
        base_url = endpoint(project, location)
        credentials, _ = default(scopes=SCOPES)
    except Exception as exc:
        raise VertexAuthUnavailable(
            "Vertex AI ADC credentials are not available. Configure Application "
            "Default Credentials or attach a service identity to the app.") from exc
    client = OpenAI(api_key="vertex-adc", base_url=base_url)
    return client, credentials, Request()


def refresh_client(client, credentials, request):
    try:
        credentials.refresh(request)
    except Exception as exc:
        raise VertexAuthUnavailable(
            "Could not refresh Vertex AI Application Default Credentials.") from exc
    if not credentials.token:
        raise VertexAuthUnavailable(
            "Vertex AI Application Default Credentials returned no access token.")
    client.api_key = credentials.token
