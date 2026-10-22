import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from delivery.catalogue import load_catalogue
from delivery.history import build_history, history_catalogue, history_manifest

START = date(2026, 1, 1)
SOURCES = {"market": "supermarket", "shop": "retail"}


def row(day: int = 0, source: str = "market", listing: str = "a") -> dict[str, Any]:
    return dict(
        source=source,
        listing_id=listing,
        name="Observed product",
        price="2.50",
        currency="USD",
        observed_on=(START + timedelta(days=day)).isoformat(),
        domain=SOURCES.get(source, "supermarket"),
        provenance="imported",
    )


def test_ten_days_explicit_gaps_and_hashes(tmp_path: Path) -> None:
    root = tmp_path / "history"
    records = [row(0), row(9, "shop")]
    records[0]["scraped_at"] = "2026-01-01T12:00:00Z"
    result = build_history(records, root, START, START + timedelta(days=9), SOURCES)
    assert result["requested_days"] == 10
    assert result["available_days"] == 2
    assert result["days"][1]["status"] == "missing"
    assert result["days"][0]["by_source"] == {"market": 1, "shop": 0}
    assert result["metadata"]["observation_basis"] == "warehouse ingestion day"
    assert history_manifest(root)["available"]
    path = history_catalogue(START, root)
    assert load_catalogue(path).digest() == result["days"][0]["sha256"]
    with pytest.raises(FileNotFoundError):
        history_catalogue(START + timedelta(days=1), root)
    with pytest.raises(FileNotFoundError):
        history_catalogue(START - timedelta(days=1), root)


def test_selection_is_stable_across_dates(tmp_path: Path) -> None:
    root = tmp_path / "history"
    records = [row(0, listing="b"), row(1, listing="a"), row(1, listing="b")]
    result = build_history(records, root, START, START + timedelta(days=1), SOURCES, 1)
    assert result["days"][0]["status"] == "missing"
    assert [
        p.listing_id
        for p in load_catalogue(history_catalogue(START + timedelta(days=1), root)).products
    ] == ["a"]


def test_empty_and_immutable(tmp_path: Path) -> None:
    root = tmp_path / "history"
    assert history_manifest(root) == {"available": False, "days": []}
    result = build_history([], root, START, START, SOURCES)
    assert result["available_days"] == 0
    before = (root / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        build_history([row()], root, START, START, SOURCES)
    assert (root / "manifest.json").read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "unknown"},
        {"domain": "retail"},
        {"price": "0"},
        {"currency": "EUR"},
        {"observed_on": "2025-12-31"},
        {"provenance": "simulated"},
    ],
)
def test_invalid_rows_rejected(tmp_path: Path, changes: dict[str, Any]) -> None:
    root = tmp_path / "history"
    with pytest.raises(ValueError):
        build_history([{**row(), **changes}], root, START, START, SOURCES)
    assert not root.exists()
    assert not list(tmp_path.glob(".history-*"))


def test_duplicates_rejected_even_if_outside_selected_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        build_history(
            [row(), row(listing="b"), row(listing="b")],
            tmp_path / "history",
            START,
            START,
            SOURCES,
            1,
        )


@pytest.mark.parametrize("tamper", ["content", "path", "day"])
def test_tampering_rejected(tmp_path: Path, tamper: str) -> None:
    root = tmp_path / "history"
    build_history([row()], root, START, START, SOURCES)
    if tamper == "content":
        path = root / f"{START}.json"
        content = json.loads(path.read_text())
        content["products"][0]["name"] = "Changed"
        path.write_text(json.dumps(content))
    else:
        path = root / "manifest.json"
        content = json.loads(path.read_text())
        content["days"][0]["file" if tamper == "path" else "date"] = "../other.json"
        path.write_text(json.dumps(content))
    with pytest.raises(ValueError):
        history_catalogue(START, root)
