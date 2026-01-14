"""Utility functions for formatting and data processing."""

import pandas as pd
from typing import Any


def format_bytes(bytes_value: int) -> str:
    """
    Format bytes to human-readable format.

    Args:
        bytes_value: Number of bytes

    Returns:
        Formatted string (e.g., "1.23 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def format_table_name(full_name: str) -> str:
    """
    Extract table name from fully qualified name.

    Args:
        full_name: Fully qualified table name (project.dataset.table)

    Returns:
        Just the table name
    """
    parts = full_name.split('.')
    return parts[-1] if parts else full_name


def infer_viz_type(df: pd.DataFrame) -> str:
    """
    Suggest visualization type based on DataFrame structure.

    Args:
        df: pandas DataFrame

    Returns:
        Suggested visualization type
    """
    if df is None or df.empty:
        return "table"

    numeric_cols = df.select_dtypes(include=['number']).columns
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns

    if len(numeric_cols) >= 2:
        return "scatter"
    elif len(numeric_cols) == 1 and len(categorical_cols) >= 1:
        return "bar"
    elif len(categorical_cols) >= 1:
        return "count"

    return "table"


def truncate_text(text: str, max_length: int = 100) -> str:
    """
    Truncate text to maximum length.

    Args:
        text: Text to truncate
        max_length: Maximum length

    Returns:
        Truncated text with ellipsis if needed
    """
    if not text:
        return ""
    return text[:max_length] + "..." if len(text) > max_length else text


def safe_get(dictionary: dict, key: str, default: Any = None) -> Any:
    """
    Safely get value from dictionary.

    Args:
        dictionary: Dictionary to query
        key: Key to look up
        default: Default value if key not found

    Returns:
        Value or default
    """
    try:
        return dictionary.get(key, default)
    except (AttributeError, TypeError):
        return default
