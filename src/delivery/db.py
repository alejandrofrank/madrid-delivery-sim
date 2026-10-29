import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from delivery.config import settings

Connection = psycopg.Connection[dict[str, Any]]

# Both immutable files were shipped under the same name on independent branches.
# Accept only this exact old/new pair; retain the original ledger hash and let
# 027 converge the schemas. A changed canonical file must still fail closed.
_MIGRATION_HISTORY = {
    "026_telemetry_context.sql": (
        "e653fefc503d701ded74ee51f6a1ebd792a275fef11d244aedd0408dda764277",
        "c1c197008648301a7e0246a8f7c985dc06c1944d3393484ca3a62df8b830d19d",
    ),
}


def _compatible_migration(name: str, current: str, applied: str) -> bool:
    return _MIGRATION_HISTORY.get(name) == (current, applied)


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
            if (
                prior
                and prior["sha256"] != checksum
                and not _compatible_migration(path.name, checksum, prior["sha256"])
            ):
                raise RuntimeError(f"Applied migration changed: {path.name}")
            if not prior:
                conn.execute(source)
                conn.execute(
                    "INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)",
                    (path.name, checksum),
                )
