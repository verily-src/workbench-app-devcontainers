from types import SimpleNamespace

import pytest

import providers
import vertexai_auth


def test_vertex_endpoint_is_fixed_to_project_and_location():
    assert vertexai_auth.endpoint("studio-project", "us-central1") == (
        "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/"
        "studio-project/locations/us-central1/endpoints/openapi")
    assert vertexai_auth.endpoint("studio-project", "global") == (
        "https://aiplatform.googleapis.com/v1beta1/projects/studio-project/"
        "locations/global/endpoints/openapi")


@pytest.mark.parametrize("project,location", [
    ("../other", "us-central1"),
    ("studio-project", "us-central1/other"),
    ("studio-project", ""),
])
def test_vertex_endpoint_rejects_invalid_config(project, location):
    with pytest.raises(ValueError):
        vertexai_auth.endpoint(project, location)


def test_vertex_provider_refreshes_adc_for_each_model_call(monkeypatch):
    calls = []
    refreshes = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append((client.api_key, kwargs))
            if len(calls) == 1:
                tool_call = SimpleNamespace(
                    id="call-1",
                    function=SimpleNamespace(name="count_rows", arguments="{}"))
                message = SimpleNamespace(
                    content=None, tool_calls=[tool_call],
                    model_dump=lambda **_: {"role": "assistant", "tool_calls": []})
            else:
                message = SimpleNamespace(
                    content="Done.", tool_calls=None,
                    model_dump=lambda **_: {"role": "assistant", "content": "Done."})
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2,
                                      total_tokens=7),
                choices=[SimpleNamespace(message=message)])

    class FakeClient:
        api_key = ""
        chat = SimpleNamespace(completions=FakeCompletions())

        def close(self):
            self.closed = True

    client = FakeClient()
    credentials = object()
    request = object()

    def refresh(fake_client, fake_credentials, fake_request):
        assert fake_credentials is credentials
        assert fake_request is request
        refreshes.append(len(refreshes) + 1)
        fake_client.api_key = f"access-token-{len(refreshes)}"

    monkeypatch.setattr(vertexai_auth, "new_client",
                        lambda project, location: (client, credentials, request))
    monkeypatch.setattr(vertexai_auth, "refresh_client", refresh)
    out = providers.run(
        "vertexai", "google/gemini-model", None, None, "system",
        [{"role": "user", "content": "count"}],
        {"count_rows": lambda: '{"count":2}'},
        vertex_config={"project": "studio-project", "location": "us-central1"})

    assert [token for token, _ in calls] == ["access-token-1", "access-token-2"]
    assert len(refreshes) == 2
    assert calls[0][1]["tools"] == providers.TOOL_SCHEMAS
    assert out["reply"] == "Done."
    assert out["tool_calls"] == ["count_rows"]
    assert out["usage"]["total_tokens"] == 14
    assert client.closed
