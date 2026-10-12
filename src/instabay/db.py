"""NFR-03, NFR-06: SQLite LLM ledger; business tables arrive in Phase 2."""

import sqlite3
from pathlib import Path

from instabay.adapters.call_store import CallRecord


class SQLiteCallStore:
    """NFR-03: persist the LLM cache across process restarts."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                output_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS llm_call (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                template_name TEXT NOT NULL,
                slot_id TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                error_type TEXT
            );
            """
        )

    def get_cached(self, cache_key: str) -> str | None:
        """NFR-03: return the stored schema-valid output, if any."""
        row = self._connection.execute(
            "SELECT output_json FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        value: object = row["output_json"]
        if not isinstance(value, str):
            raise TypeError("Cached output must be JSON text")
        return value

    def put_cached(self, cache_key: str, output_json: str) -> None:
        """NFR-03: persist successful output atomically."""
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, output_json) VALUES (?, ?)",
                (cache_key, output_json),
            )

    def delete_cached(self, cache_key: str) -> None:
        """NFR-03: evict corrupt cache entries before replaying the provider."""
        with self._connection:
            self._connection.execute("DELETE FROM llm_cache WHERE cache_key = ?", (cache_key,))

    def log_call(self, record: CallRecord) -> None:
        """NFR-06: append a Pydantic-validated call row using bound parameters."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO llm_call VALUES (
                    :id, :created_at, :template_name, :slot_id, :model, :prompt_hash,
                    :cache_key, :status, :attempt, :latency_ms, :input_tokens,
                    :output_tokens, :cost_usd, :error_type
                )
                """,
                record.model_dump(mode="json"),
            )

    def calls(self) -> list[CallRecord]:
        """NFR-06: read call rows through their validated boundary model."""
        rows = self._connection.execute("SELECT * FROM llm_call ORDER BY rowid").fetchall()
        return [CallRecord.model_validate(dict(row)) for row in rows]

    def close(self) -> None:
        """NFR-06: explicitly release the database connection."""
        self._connection.close()

    def __enter__(self) -> "SQLiteCallStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
