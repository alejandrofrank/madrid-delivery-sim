"""Immutable, local daily catalogues with explicit gaps in observation history."""

import json
import os
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from delivery.catalogue import Catalogue, Product, load_catalogue

DEFAULT_ROOT = Path("data/local/bakiano")


def build_history(
    rows: list[dict[str, Any]],
    output: Path,
    start: date,
    end: date,
    sources: dict[str, str],
    per_source: int = 50,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate every row, select stable identities, and publish a new directory."""
    if output.exists():
        raise FileExistsError(output)
    if start > end or not 1 <= per_source <= 500:
        raise ValueError("Ordered dates and per_source 1..500 required")
    if not sources or any(
        not source.strip() or domain not in {"supermarket", "retail"}
        for source, domain in sources.items()
    ):
        raise ValueError("Sources must map nonempty names to supermarket or retail")
    products: list[Product] = []
    identities: set[tuple[date, str, str]] = set()
    timestamps: dict[str, set[str]] = {source: set() for source in sources}
    for row in rows:
        product = Product.model_validate({k: v for k, v in row.items() if k != "scraped_at"})
        if product.source not in sources or product.domain != sources[product.source]:
            raise ValueError("Unknown source or source/domain mismatch")
        if product.provenance != "imported" or not start <= product.observed_on <= end:
            raise ValueError("Imported observations within the requested dates required")
        identity = (product.observed_on, product.source, product.listing_id)
        if identity in identities:
            raise ValueError("Duplicate source listing identity for day")
        identities.add(identity)
        products.append(product)
        if row.get("scraped_at") is not None:
            timestamps[product.source].add(str(row["scraped_at"]))
    selected = {
        source: set(sorted({p.listing_id for p in products if p.source == source})[:per_source])
        for source in sources
    }
    days: list[dict[str, Any]] = []
    catalogues: dict[str, Catalogue] = {}
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        daily = sorted(
            (p for p in products if p.observed_on == day and p.listing_id in selected[p.source]),
            key=lambda p: (p.domain != "supermarket", p.source, p.listing_id),
        )
        catalogue = (
            Catalogue(origin="Bakiano local dated observations", products=daily) if daily else None
        )
        filename = f"{day.isoformat()}.json" if catalogue else None
        if filename and catalogue:
            catalogues[filename] = catalogue
        days.append(
            {
                "date": day.isoformat(),
                "status": "available" if daily else "missing",
                "file": filename,
                "products": len(daily),
                "by_source": {
                    source: sum(p.source == source for p in daily) for source in sorted(sources)
                },
                "sha256": catalogue.digest() if catalogue else None,
            }
        )
    details = dict(metadata or {})
    details["observation_basis"] = "warehouse ingestion day"
    if any(timestamps.values()):
        details["source_collection_timestamps"] = {
            source: sorted(values) for source, values in sorted(timestamps.items())
        }
    manifest = {
        "schema_version": 1,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "requested_days": len(days),
        "available_days": len(catalogues),
        "sources": dict(sorted(sources.items())),
        "per_source_limit": per_source,
        "metadata": details,
        "days": days,
    }
    # Serialize before creating staging, so invalid metadata cannot leave partial exports.
    serialized = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for filename, catalogue in catalogues.items():
            (staging / filename).write_text(
                catalogue.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        (staging / "manifest.json").write_text(serialized, encoding="utf-8")
        if output.exists():
            raise FileExistsError(output)
        os.replace(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def history_manifest(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    """Read the local index, checking its date coverage and safe catalogue names."""
    if not root.exists():
        return {"available": False, "days": []}
    manifest: dict[str, Any] = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    try:
        start, end = date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"])
        days = manifest["days"]
        if manifest["schema_version"] != 1 or start > end:
            raise ValueError("Invalid history schema or date range")
        expected = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
        if [entry["date"] for entry in days] != expected:
            raise ValueError("History days do not match requested range")
        available = 0
        for entry in days:
            if entry["status"] == "available":
                available += 1
                if entry["file"] != f"{entry['date']}.json" or entry["products"] < 1:
                    raise ValueError("Invalid history catalogue entry")
            elif (
                entry["status"] != "missing"
                or any(entry[key] is not None for key in ("file", "sha256"))
                or entry["products"] != 0
            ):
                raise ValueError("Invalid missing day entry")
        if manifest["requested_days"] != len(days) or manifest["available_days"] != available:
            raise ValueError("Invalid history day counts")
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid history manifest") from exc
    return {**manifest, "available": True}


def history_catalogue(day: date, root: Path = DEFAULT_ROOT) -> Path:
    """Resolve an indexed day only after verifying its catalogue and content hash."""
    manifest = history_manifest(root)
    entry = next((item for item in manifest["days"] if item["date"] == day.isoformat()), None)
    if entry is None or entry["status"] != "available":
        raise FileNotFoundError(f"No observed catalogue for {day.isoformat()}")
    path = root / entry["file"]
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError("Catalogue must be a local history file")
    catalogue = load_catalogue(path)
    if catalogue.digest() != entry["sha256"]:
        raise ValueError("History catalogue hash mismatch")
    counts = {source: 0 for source in manifest["sources"]}
    for product in catalogue.products:
        if (
            product.observed_on != day
            or product.source not in counts
            or product.domain != manifest["sources"][product.source]
            or product.provenance != "imported"
        ):
            raise ValueError("Catalogue observations do not match history manifest")
        counts[product.source] += 1
    if counts != entry["by_source"] or len(catalogue.products) != entry["products"]:
        raise ValueError("Catalogue counts do not match history manifest")
    return path
