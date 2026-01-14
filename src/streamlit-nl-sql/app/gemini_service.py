"""Vertex AI Gemini integration for natural language to SQL conversion."""

import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from typing import Dict, Optional, List
import json
import re
from config import AppConfig


class GeminiNLToSQL:
    """Converts natural language to SQL using Vertex AI Gemini."""

    def __init__(self, config: AppConfig):
        """
        Initialize Gemini NL-to-SQL service.

        Args:
            config: Application configuration
        """
        self.config = config
        vertexai.init(project=config.project_id, location=config.location)
        self.model = GenerativeModel(config.gemini_model)
        self.generation_config = GenerationConfig(
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens
        )

    def generate_sql(
        self,
        natural_language_query: str,
        dataset_schema: Optional[Dict] = None,
        conversation_history: Optional[List] = None
    ) -> Dict[str, str]:
        """
        Convert natural language to SQL.

        Args:
            natural_language_query: User's natural language question
            dataset_schema: Optional schema information for context
            conversation_history: Optional previous queries for context

        Returns:
            Dict with 'sql', 'explanation', 'confidence', and optional 'error'
        """
        prompt = self._build_prompt(
            natural_language_query,
            dataset_schema,
            conversation_history
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=self.generation_config
            )

            return self._parse_response(response.text)

        except Exception as e:
            return {
                "sql": None,
                "explanation": f"Error generating SQL: {str(e)}",
                "confidence": "low",
                "error": str(e)
            }

    def _build_prompt(
        self,
        query: str,
        schema: Optional[Dict] = None,
        history: Optional[List] = None
    ) -> str:
        """
        Build the prompt for Gemini.

        Args:
            query: Natural language query
            schema: Optional dataset schema
            history: Optional conversation history

        Returns:
            Complete prompt string
        """
        prompt_parts = [
            "You are an expert SQL query generator for Google BigQuery.",
            "",
            "Task: Convert the following natural language query into a valid BigQuery SQL SELECT statement.",
            "",
            "Requirements:",
            "1. Generate ONLY SELECT statements",
            "2. Use standard SQL syntax (not legacy SQL)",
            "3. Include appropriate WHERE, GROUP BY, ORDER BY, and LIMIT clauses as needed",
            "4. Use table names with fully qualified paths: project.dataset.table",
            "5. Optimize for performance (use LIMIT when appropriate, default to LIMIT 100 if not specified)",
            "6. Handle NULL values appropriately",
            "7. Use meaningful column aliases for readability",
            "8. Do NOT include any DDL or DML operations (DROP, DELETE, UPDATE, INSERT, etc.)",
            "",
        ]

        # Add schema context if available
        if schema and isinstance(schema, dict) and "error" not in schema:
            prompt_parts.extend([
                "Available Tables and Columns:",
                "---"
            ])
            for table_name, columns in schema.items():
                if isinstance(columns, list):
                    prompt_parts.append(f"\nTable: {table_name}")
                    for col in columns[:20]:  # Limit to first 20 columns
                        if isinstance(col, dict):
                            prompt_parts.append(
                                f"  - {col.get('name', 'unknown')} ({col.get('type', 'unknown')})"
                            )
            prompt_parts.append("---")
            prompt_parts.append("")

        # Add conversation history if available
        if history and len(history) > 0:
            prompt_parts.extend([
                "Previous Context (for reference):",
                "---"
            ])
            for item in history[-3:]:  # Last 3 queries
                if isinstance(item, dict):
                    prompt_parts.append(f"Q: {item.get('nl_query', '')}")
                    prompt_parts.append(f"SQL: {item.get('sql', '')}")
                    prompt_parts.append("")
            prompt_parts.append("---")
            prompt_parts.append("")

        prompt_parts.extend([
            f"Natural Language Query: {query}",
            "",
            "Response Format (JSON):",
            "{",
            '  "sql": "YOUR SQL QUERY HERE",',
            '  "explanation": "Brief explanation of what the query does",',
            '  "confidence": "high|medium|low"',
            "}",
            "",
            "Generate the SQL query now:"
        ])

        return "\n".join(prompt_parts)

    def _parse_response(self, response_text: str) -> Dict[str, str]:
        """
        Parse Gemini's response to extract SQL and metadata.

        Args:
            response_text: Raw response from Gemini

        Returns:
            Dict with sql, explanation, and confidence
        """
        # Try to extract JSON response
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)

        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return {
                    "sql": parsed.get("sql", "").strip(),
                    "explanation": parsed.get("explanation", ""),
                    "confidence": parsed.get("confidence", "medium")
                }
            except json.JSONDecodeError:
                pass

        # Fallback: try to extract SQL from code blocks
        sql_match = re.search(
            r'```(?:sql)?\n(.*?)\n```',
            response_text,
            re.DOTALL | re.IGNORECASE
        )
        if sql_match:
            return {
                "sql": sql_match.group(1).strip(),
                "explanation": "SQL extracted from code block",
                "confidence": "medium"
            }

        # Last resort: return cleaned response as SQL
        # Remove common non-SQL text
        cleaned = response_text.strip()
        for prefix in ["Here's the SQL:", "Here is the SQL:", "SQL:", "Query:"]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        return {
            "sql": cleaned,
            "explanation": "Could not parse structured response",
            "confidence": "low"
        }
