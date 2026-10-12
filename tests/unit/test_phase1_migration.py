"""NFR-03: Phase 1 call records survive the nullable run-scope migration."""

import sqlite3
from pathlib import Path

from instabay.db import SQLiteCallStore


def test_existing_call_table_is_migrated_without_losing_usage_or_cache(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE llm_call (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                template_name TEXT NOT NULL, slot_id TEXT NOT NULL, model TEXT NOT NULL,
                prompt_hash TEXT NOT NULL, cache_key TEXT NOT NULL, status TEXT NOT NULL,
                attempt INTEGER NOT NULL, latency_ms REAL NOT NULL,
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL, error_type TEXT
            );
            CREATE TABLE llm_cache (cache_key TEXT PRIMARY KEY, output_json TEXT NOT NULL);
        """)
        connection.execute(
            "INSERT INTO llm_call VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy",
                "2026-10-12T01:00:00+00:00",
                "copy_en",
                "wk42-tue-1",
                "fake-fixture-v1",
                "a" * 64,
                "b" * 64,
                "success",
                1,
                12.5,
                150,
                55,
                0,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO llm_cache VALUES (?, ?)",
            ("b" * 64, '{"caption":"quiet","alt_text":"water"}'),
        )
    with SQLiteCallStore(path) as store:
        record = store.calls()[0]
        assert record.id == "legacy"
        assert record.input_tokens == 150 and record.output_tokens == 55
        assert record.run_id is None
        assert store.get_cached("b" * 64) == '{"caption":"quiet","alt_text":"water"}'
