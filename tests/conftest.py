import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest

from delivery.db import connect, migrate


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to the dedicated integration test database")
    if url.rsplit("/", 1)[-1] != "delivery_test":
        raise RuntimeError("Integration tests require the dedicated delivery_test database")
    migrate(url)
    return url


@pytest.fixture
def run_id(db_url: str) -> Iterator[UUID]:
    run = uuid4()
    with connect(db_url) as conn:
        conn.execute("INSERT INTO runs(id,seed) VALUES (%s,42)", (run,))
    yield run
    with connect(db_url) as conn:
        for table in (
            "llm_requests",
            "decisions",
            "complaints",
            "orders",
            "couriers",
            "events",
            "runs",
        ):
            field = "id" if table == "runs" else "run_id"
            conn.execute(f"DELETE FROM {table} WHERE {field}=%s", (run,))
