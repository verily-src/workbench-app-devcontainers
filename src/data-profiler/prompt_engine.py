"""
Gemini client for WB Data Profiler.

Provides:
  - Model auto-detection (tries latest flash models first, falls back)
  - Shared call_gemini() with configurable model
  - JSON extraction from LLM responses
"""

from __future__ import annotations

import json
import re
from typing import Optional

DEFAULT_LOCATION = "us-central1"

_MODEL_CANDIDATES = [
    "gemini-2.5-flash",
]


def detect_available_model(
    project_id: Optional[str] = None,
    location: str = DEFAULT_LOCATION,
) -> str:
    """
    Probe Vertex AI for the best available Gemini flash model.
    A model is considered available if the call doesn't raise a 404.
    """
    from google import genai
    from google.genai.types import GenerateContentConfig

    client = genai.Client(vertexai=True, project=project_id, location=location)
    config = GenerateContentConfig(temperature=0.1, max_output_tokens=32)

    for model in _MODEL_CANDIDATES:
        try:
            resp = client.models.generate_content(
                model=model,
                contents="What is 2+2? Reply with just the number.",
                config=config,
            )
            # Model is available if we get here without a 404
            print(f"  Model detected: {model}")
            return model
        except Exception as e:
            print(f"  Model {model} not available: {e}")
            continue

    raise RuntimeError(
        f"No Gemini model available in project {project_id}. "
        f"Tried: {', '.join(_MODEL_CANDIDATES)}. "
        "Check Vertex AI API is enabled and your project has model access."
    )


def call_gemini(
    system_prompt: str,
    user_message: str,
    model_name: str,
    project_id: Optional[str] = None,
    location: str = DEFAULT_LOCATION,
    temperature: float = 0.1,
    max_output_tokens: int = 65536,
) -> str:
    """
    Call Gemini via the google-genai SDK (Vertex AI backend).

    ADC handles auth automatically on Workbench.
    For local testing: `gcloud auth application-default login`.
    """
    from google import genai
    from google.genai.types import GenerateContentConfig

    client = genai.Client(vertexai=True, project=project_id, location=location)

    config = GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    response = client.models.generate_content(
        model=model_name,
        contents=user_message,
        config=config,
    )
    return response.text


def extract_json_from_response(response: str) -> Optional[dict | list]:
    """
    Extract a JSON object or array from an LLM response.
    Tries ```json blocks first, then bare ``` blocks, then the full text.
    """
    for pattern in [r"```json\s*\n(.*?)```", r"```\s*\n(.*?)```"]:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue

    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    return None
