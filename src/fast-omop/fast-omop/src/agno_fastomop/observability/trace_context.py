"""
Trace context sharing between fastomop and OMCP subprocess.
Uses a temporary file to pass dynamic trace context across process boundaries.
Supports W3C Trace Context format via OpenTelemetry propagation.
"""
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Optional, Dict
from opentelemetry.propagate import inject


# Use platform-specific temp directory for cross-platform compatibility
# if platform.system() == "Windows":
#     TRACE_CONTEXT_FILE = Path(tempfile.gettempdir()) / ".fastomop_langfuse_trace_context.json"
# else:
#     # On Unix-like systems (macOS/Linux), use /tmp for consistency
#     TRACE_CONTEXT_FILE = Path("/tmp") / ".fastomop_langfuse_trace_context.json"
TRACE_CONTEXT_FILE = Path("/var/log/fastomop") / ".fastomop_langfuse_trace_context.json"


def write_trace_context_otel(session_id: Optional[str] = None) -> None:
    """
    Write current OpenTelemetry trace context to shared file for OMCP subprocess.
    Uses W3C Trace Context format (traceparent/tracestate).

    Args:
        session_id: Optional session identifier for grouping traces
    """
    # Extract current OpenTelemetry context using W3C Trace Context format
    carrier: Dict[str, str] = {}
    inject(carrier)  # Populates carrier with 'traceparent' and optionally 'tracestate'

    context = {
        "traceparent": carrier.get("traceparent"),
        "tracestate": carrier.get("tracestate"),
        "session_id": session_id,
        "timestamp": str(os.times().elapsed),
    }

    try:
        # Atomic write using temp file + rename
        temp_file = TRACE_CONTEXT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(context, f)
        temp_file.replace(TRACE_CONTEXT_FILE)
    except Exception as e:
        # Non-critical error, log but don't fail
        print(f"Warning: Failed to write trace context: {e}")


def write_trace_context(trace_id: Optional[str], observation_id: Optional[str], session_id: Optional[str] = None) -> None:
    """
    DEPRECATED: Legacy function for backward compatibility.
    Use write_trace_context_otel() instead for proper OpenTelemetry integration.

    Write current trace context to shared file for OMCP subprocess.

    Args:
        trace_id: Current Langfuse trace ID
        observation_id: Current Langfuse observation ID (parent for OMCP spans)
        session_id: Optional session identifier for grouping traces
    """
    context = {
        "trace_id": trace_id,
        "parent_observation_id": observation_id,
        "session_id": session_id,
        "timestamp": str(os.times().elapsed),  # Simple timestamp
    }

    try:
        # Atomic write using temp file + rename
        temp_file = TRACE_CONTEXT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(context, f)
        temp_file.replace(TRACE_CONTEXT_FILE)
    except Exception as e:
        # Non-critical error, log but don't fail
        print(f"Warning: Failed to write trace context: {e}")


def read_trace_context() -> Dict[str, Optional[str]]:
    """
    Read current trace context from shared file.

    Returns:
        Dict with trace_id, parent_observation_id, and session_id (or None if not available)
    """
    try:
        if TRACE_CONTEXT_FILE.exists():
            with open(TRACE_CONTEXT_FILE, 'r') as f:
                context = json.load(f)
                return {
                    "trace_id": context.get("trace_id"),
                    "parent_observation_id": context.get("parent_observation_id"),
                    "session_id": context.get("session_id"),
                }
    except Exception as e:
        # Non-critical error, return empty context
        print(f"Warning: Failed to read trace context: {e}")

    return {
        "trace_id": None,
        "parent_observation_id": None,
        "session_id": None,
    }


def clear_trace_context() -> None:
    """Clear the trace context file."""
    try:
        if TRACE_CONTEXT_FILE.exists():
            TRACE_CONTEXT_FILE.unlink()
    except Exception:
        pass  # Ignore errors
