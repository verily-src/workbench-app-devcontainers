"""SQL validation and security layer for preventing injection attacks."""

import sqlparse
from sqlparse.tokens import Keyword, DML
from typing import Tuple
from config import AppConfig


class SQLValidator:
    """Validates and sanitizes SQL queries for security."""

    def __init__(self, config: AppConfig):
        """
        Initialize SQL validator.

        Args:
            config: Application configuration with security settings
        """
        self.config = config
        self.blocked_keywords = set(kw.upper() for kw in config.blocked_keywords)
        self.allowed_operations = set(op.upper() for op in config.allowed_sql_operations)

    def validate_query(self, sql: str) -> Tuple[bool, str]:
        """
        Validate SQL query for security issues.

        Args:
            sql: SQL query to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not sql or not sql.strip():
            return False, "Empty query"

        # Check query size
        if len(sql) > self.config.max_query_size_kb * 1024:
            return False, f"Query exceeds maximum size of {self.config.max_query_size_kb}KB"

        # Parse SQL
        try:
            parsed = sqlparse.parse(sql)
        except Exception as e:
            return False, f"SQL parsing error: {str(e)}"

        if not parsed:
            return False, "Could not parse query"

        # Check for multiple statements
        if len(parsed) > 1:
            return False, "Multiple SQL statements not allowed (security risk)"

        statement = parsed[0]

        # Check statement type
        stmt_type = statement.get_type()
        if stmt_type not in self.allowed_operations:
            return False, f"Operation '{stmt_type}' not allowed. Only {', '.join(self.allowed_operations)} permitted"

        # Extract all tokens
        tokens = [token.value.upper() for token in statement.flatten()
                 if token.ttype is Keyword or token.ttype is DML]

        # Check for blocked keywords
        blocked_found = self.blocked_keywords.intersection(tokens)
        if blocked_found:
            return False, f"Blocked SQL keywords detected: {', '.join(sorted(blocked_found))}"

        # For SELECT statements, ensure FROM clause exists
        if stmt_type == "SELECT":
            if not self._has_from_clause(statement):
                return False, "SELECT queries must include a FROM clause"

        return True, "Query validated successfully"

    def _has_from_clause(self, statement) -> bool:
        """
        Check if statement has a FROM clause.

        Args:
            statement: Parsed SQL statement

        Returns:
            True if FROM clause exists
        """
        for token in statement.tokens:
            if token.ttype is Keyword and token.value.upper() == 'FROM':
                return True
            # Check nested tokens
            if hasattr(token, 'tokens'):
                for subtoken in token.tokens:
                    if subtoken.ttype is Keyword and subtoken.value.upper() == 'FROM':
                        return True
        return False

    def sanitize_query(self, sql: str) -> str:
        """
        Format and sanitize SQL query.

        Args:
            sql: SQL query to sanitize

        Returns:
            Formatted SQL query
        """
        return sqlparse.format(
            sql,
            reindent=True,
            keyword_case='upper',
            strip_comments=True
        )
