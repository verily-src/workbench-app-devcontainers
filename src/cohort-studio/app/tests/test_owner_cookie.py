import hashlib

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from agent_sessions import owner, preserve_owner_cookie


def test_page_sets_owner_before_api_requests():
    app = FastAPI()
    app.middleware("http")(preserve_owner_cookie)

    @app.get("/")
    def page():
        return {"page": True}

    @app.get("/api/owner")
    def api(request: Request, response: Response):
        return {"owner": owner(request, response)}

    with TestClient(app) as client:
        page_response = client.get("/")
        cookie = page_response.cookies["studio_chat_owner"]
        expected = hashlib.sha256(cookie.encode()).hexdigest()
        for _ in range(2):
            response = client.get("/api/owner")
            assert response.json()["owner"] == expected
            assert "set-cookie" not in response.headers
