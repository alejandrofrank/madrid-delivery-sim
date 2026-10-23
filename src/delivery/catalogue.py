"""Offline catalogue boundary. Observed listings never imply physical stock."""

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str = Field(min_length=1)
    listing_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Literal["USD"] = "USD"
    observed_on: date
    category: str | None = None
    url: str | None = None
    provenance: Literal["imported", "simulated"]
    domain: Literal["supermarket", "retail", "pharmacy"] = "supermarket"


class Catalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    origin: str
    products: list[Product] = Field(min_length=1)

    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_catalogue(path: Path) -> Catalogue:
    catalogue = Catalogue.model_validate_json(path.read_text(encoding="utf-8"))
    identities = [(p.source, p.listing_id) for p in catalogue.products]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate source listing identity")
    return catalogue


def import_bakiano_csv(
    path: Path,
    source: str,
    limit: int = 50,
    domain: Literal["supermarket", "retail"] = "retail",
) -> Catalogue:
    """Read Bakiano collector exports; preserve raw prices with explicit USD-only guard.

    Caller must select an export whose prices are genuinely USD (e.g. Daka), not
    a raw vendor series with mislabeled bolivares. No currency inference is made.
    """
    if not source.strip() or not 1 <= limit <= 500:
        raise ValueError("Source and limit 1..500 required")
    products: list[Product] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"code", "name", "price", "timestamp"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Expected Bakiano collector code/name/price/timestamp columns")
        for row in reader:
            if len(products) == limit:
                break
            products.append(
                Product(
                    source=source,
                    listing_id=row["code"],
                    name=row["name"],
                    price=Decimal(row["price"]),
                    observed_on=date.fromisoformat(row["timestamp"][:10]),
                    category=row.get("category") or None,
                    url=row.get("url") or None,
                    provenance="imported",
                    domain=domain,
                )
            )
    catalogue = Catalogue(
        origin=f"Bakiano collector export; sha256={hashlib.sha256(path.read_bytes()).hexdigest()}",
        products=products,
    )
    identities = [(p.source, p.listing_id) for p in products]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate source listing identity")
    return catalogue
