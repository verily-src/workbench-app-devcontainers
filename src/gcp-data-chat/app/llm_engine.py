"""
LLM chat engine with inline chart/histogram generation.
When the user asks for a chart, the LLM returns Python matplotlib code
which the server executes against the loaded DataFrame and returns as base64 PNG.
"""
import base64
import io
import re
import traceback

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from openai import OpenAI


OPENAI_US_BASE_URL = "https://us.api.openai.com/v1/"

SYSTEM_PROMPT = """You are a helpful data analyst assistant. The user is asking questions about a dataset loaded in a Python pandas DataFrame called `df`.
You have access to the dataset's schema, statistics, and a sample of the data. Use this context to answer accurately.

IMPORTANT RULES:
1. For text questions (describe, explain, summarize, list columns, value ranges, etc.), respond with clear, well-formatted markdown text.

2. When the user asks for a CHART, HISTOGRAM, PLOT, DISTRIBUTION, or VISUALIZATION:
   - You MUST include a Python code block wrapped in ```python:chart markers.
   - The code MUST use matplotlib (plt). The DataFrame is available as `df`. numpy is available as `np`.
   - Do NOT call plt.show(). The system captures the figure automatically.
   - Always set a clear title with plt.title().
   - Always call plt.tight_layout() at the end.
   - Use attractive colors (e.g. '#4285F4', '#34A853', '#EA4335', '#FBBC05', '#5F6368').
   - For histograms of categorical data with many unique values, show only the top 20-30.
   - Example:
     ```python:chart
     plt.figure(figsize=(10, 6))
     df['column_name'].dropna().hist(bins=30, color='#4285F4', edgecolor='white')
     plt.title('Distribution of column_name')
     plt.xlabel('Value')
     plt.ylabel('Frequency')
     plt.tight_layout()
     ```

3. You may combine a text explanation WITH a chart code block in the same response.

4. Be concise and helpful. Use markdown formatting (bold, lists, tables) for readability.

5. If the question cannot be answered from the available data context, say so.

6. For multi-column charts, use subplots or grouped bars. Always label axes clearly."""


def _extract_chart_code(text: str) -> tuple[str, str]:
    """Extract python:chart code from the LLM response.
    Returns (cleaned_text, chart_code). chart_code is '' if not found.
    """
    pattern = r"```python:chart\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        clean = re.sub(pattern, "\n\n**[Chart generated below]**\n\n", text, flags=re.DOTALL)
        return clean.strip(), code
    return text, ""


def _execute_chart_code(code: str, df: pd.DataFrame) -> tuple[str | None, str | None]:
    """Execute matplotlib code against the DataFrame.
    Returns (base64_png_or_None, error_message_or_None).
    """
    try:
        plt.close("all")
        local_vars = {
            "df": df,
            "pd": pd,
            "np": np,
            "plt": plt,
            "matplotlib": matplotlib,
        }
        exec(code, {"__builtins__": __builtins__}, local_vars)

        fig = plt.gcf()
        if fig.get_axes():
            buf = io.BytesIO()
            fig.savefig(
                buf,
                format="png",
                dpi=150,
                bbox_inches="tight",
                facecolor="white",
                edgecolor="none",
            )
            buf.seek(0)
            b64 = base64.b64encode(buf.read()).decode("utf-8")
            plt.close("all")
            return b64, None
        plt.close("all")
        return None, "Chart code ran but produced no figure."
    except Exception as e:
        plt.close("all")
        return None, f"Chart code error: {e}"


def chat_with_data(
    api_key: str,
    data_summary: str,
    schema_and_sample: str,
    question: str,
    df: pd.DataFrame,
    model: str = "gpt-4o-mini",
    use_us_endpoint: bool = True,
    chat_history: list[dict] | None = None,
) -> dict:
    """
    Chat with data using the LLM. Returns dict with:
      - 'text': markdown response
      - 'chart': base64 PNG string or None
    """
    base_url = OPENAI_US_BASE_URL if use_us_endpoint else "https://api.openai.com/v1"
    client = OpenAI(api_key=api_key.strip(), base_url=base_url)

    # Build data context for LLM
    user_content = (
        f"## Data summary\n{data_summary}\n\n"
        f"## Schema and sample\n{schema_and_sample}\n\n"
        f"## User question\n{question}"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if chat_history:
        # Include recent history (last 10 exchanges) to maintain context
        recent = chat_history[-10:]
        for msg in recent:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_content})

    response = client.chat.completions.create(
        model=model.strip() or "gpt-4o-mini",
        messages=messages,
        max_tokens=2048,
        temperature=0.3,
    )

    raw_text = response.choices[0].message.content

    # Check for chart code in the response
    clean_text, chart_code = _extract_chart_code(raw_text)

    chart_b64 = None
    if chart_code:
        chart_b64, chart_error = _execute_chart_code(chart_code, df)
        if chart_error:
            clean_text += f"\n\n> *Note: {chart_error}*"

    return {
        "text": clean_text,
        "chart": chart_b64,
    }
