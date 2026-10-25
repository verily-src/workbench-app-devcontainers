"""SQLite persistence and full-text search for the knowledge base."""

import hashlib
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import config


class KnowledgeStoreFull(RuntimeError):
    pass


class KnowledgeStore:
    def __init__(self, path: Path | None = None):
        self._configured_path = path

    @property
    def path(self) -> Path:
        return self._configured_path or Path(os.environ.get(
            "STUDIO_KNOWLEDGE_PATH",
            str(config.CONFIG_PATH.with_name("knowledge.sqlite3"))))

    @contextmanager
    def connection(self, path: Path | None = None) -> Iterator[sqlite3.Connection]:
        selected = path or self.path
        selected.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(selected, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        db = sqlite3.connect(selected, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, title TEXT NOT NULL, digest TEXT UNIQUE NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(document_id UNINDEXED, passage UNINDEXED, title, text, tokenize='unicode61')")
            with db:
                yield db
        finally:
            db.close()

    def list_documents(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, title, created_at FROM documents "
                "ORDER BY created_at DESC, id")]

    def add_document(self, title: str, text: str) -> dict:
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id, title, created_at FROM documents WHERE digest = ?",
                (digest,)).fetchone()
            if existing:
                return dict(existing)
            if db.execute("SELECT count(*) FROM documents").fetchone()[0] >= 100:
                raise KnowledgeStoreFull(
                    "Knowledge base is full (100 documents). Remove a document first.")
            identifier = uuid.uuid4().hex
            db.execute("INSERT INTO documents (id,title,digest) VALUES (?,?,?)",
                       (identifier, title, digest))
            for index, offset in enumerate(range(0, len(text), 1600), 1):
                db.execute("INSERT INTO passages VALUES (?,?,?,?)",
                           (identifier, index, title, text[offset:offset + 1800]))
            row = db.execute(
                "SELECT id,title,created_at FROM documents WHERE id=?",
                (identifier,)).fetchone()
            return dict(row)

    def delete_document(self, document_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM passages WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))

    def search(self, query: str, limit: int = 5) -> list[dict]:
        return self._search(self.path, query, limit)

    def search_existing(self, query: str, limit: int = 5) -> list[dict]:
        path = self.path
        if not path.exists():
            return []
        return self._search(path, query, limit)

    def _search(self, path: Path, query: str, limit: int) -> list[dict]:
        terms = list(dict.fromkeys(re.findall(r"\w+", query.lower())))[:32]
        if not terms:
            return []
        expression = " OR ".join('"' + term + '"' for term in terms)
        with self.connection(path) as db:
            rows = db.execute(
                "SELECT document_id, passage, title, text FROM passages "
                "WHERE passages MATCH ? ORDER BY bm25(passages), document_id, "
                "passage LIMIT ?", (expression, limit))
            return [{**dict(row),
                     "citation": f"KB:{row['document_id']}:{row['passage']}"}
                    for row in rows]
