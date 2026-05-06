import os
import base64
from langfuse import Langfuse
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def setup_langfuse():
    """
    Setup Langfuse client for prompt management
    """
    langfuse = Langfuse(
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )

    if not langfuse.auth_check():
        raise RuntimeError("Failed to authenticate with Langfuse")

    return langfuse

@lru_cache(maxsize=1)
def get_langfuse_client():
    """
    Get Langfuse client
    """
    return setup_langfuse()
