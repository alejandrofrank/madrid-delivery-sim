import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from delivery.config import settings

Connection = psycopg.Connection[dict[str, Any]]


@contextmanager
def connect(url: str | None = None) -> Iterator[Connection]:
    with psycopg.connect(
        url or settings().database_url, row_factory=dict_row, connect_timeout=5
    ) as conn:
        yield conn


def migrate(url: str | None = None) -> None:
    with connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(918274)")
        conn.execute(Path("sql/schema.sql").read_text())
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz DEFAULT now())""")
        for path in sorted(Path("sql/migrations").glob("*.sql")):
            source = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(source.encode()).hexdigest()
            prior = conn.execute(
                "SELECT sha256 FROM schema_migrations WHERE name=%s", (path.name,)
            ).fetchone()
            if prior and prior["sha256"] != checksum:
                raise RuntimeError(f"Applied migration changed: {path.name}")
            if not prior:
                conn.execute(source)
                conn.execute(
                    "INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)",
                    (path.name, checksum),
                )
