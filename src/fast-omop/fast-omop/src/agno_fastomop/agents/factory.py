from agno.models.anthropic import Claude
from agno.models.azure import AzureOpenAI
from agno.models.openai import OpenAIChat
from agno.models.ollama import Ollama
from typing import Dict, Any
import os

def create_model(config: Dict) -> Any:
    """
    Create models as per provider settings
    """
    
    model_type = config.get("MODEL_TYPE", "anthropic")
    model_id = config.get("MODEL_ID", "claude-3-5-sonnet-20241022")

    if model_type == "anthropic":
        return Claude(id=model_id)
    elif model_type == "azure":
        return AzureOpenAI(id=model_id,
                           api_version=config.get("api_version", "2024-10-21"),
                           azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                           azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                           temperature=config.get("temperature")
                           )
    elif model_type == "openai":
        return OpenAIChat(id=model_id)
    elif model_type == "ollama":
        return Ollama(id=model_id)
    else:
        raise ValueError(f"Unknown model type: {model_type}")