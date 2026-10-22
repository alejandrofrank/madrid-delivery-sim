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
        conn.execute(Path("sql/schema.sql").read_text())
