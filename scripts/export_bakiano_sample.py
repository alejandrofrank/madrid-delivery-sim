"""Opt-in, bounded read-only extraction. Never required by local demo startup."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from delivery.history import build_history

SOURCES = {
    "madeirense": "supermarket",
    "plazas": "supermarket",
    "gama": "supermarket",
    "daka": "retail",
    "epa": "retail",
}
MAX_BYTES = 1024**3


def query_for(project: str, start: date, end: date, limit: int) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
        raise ValueError("Invalid project ID")
    return f"""
WITH observations AS (
  SELECT 'supermarket' AS domain, source, product_id AS listing_id,
         product_name AS name, price_current, category, url, ingestion_date AS observed_on,
         scraped_at
  FROM `{project}.raw_supermarket.products`
  WHERE ingestion_date BETWEEN DATE '{start}' AND DATE '{end}'
    AND source IN ('madeirense','plazas','gama')
  UNION ALL
  SELECT 'retail', source, product_id, product_name, price_current, category, url,
         ingestion_date, scraped_at
  FROM `{project}.raw_retail.products`
  WHERE ingestion_date BETWEEN DATE '{start}' AND DATE '{end}'
    AND source IN ('daka','epa')
), clean AS (
  SELECT o.* FROM observations o
  JOIN `{project}.internal_operations.vendors` v
    ON o.source=v.vendor_name AND o.domain=v.domain
  WHERE v.price_currency='USD' AND o.listing_id IS NOT NULL AND o.listing_id!=''
    AND o.name IS NOT NULL AND o.name!='' AND o.price_current>0
    AND NOT IS_INF(o.price_current) AND NOT IS_NAN(o.price_current)
    AND ROUND(o.price_current,2)>0
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY o.source,o.listing_id,o.observed_on
    ORDER BY o.scraped_at DESC,o.name,o.price_current DESC,o.url) = 1
), sampled AS (
  SELECT *, DENSE_RANK() OVER (PARTITION BY source ORDER BY listing_id) AS sample_rank
  FROM clean
)
SELECT source, listing_id, name, CAST(ROUND(price_current,2) AS STRING) AS price,
       'USD' AS currency, CAST(observed_on AS STRING) AS observed_on,
       domain, category, url, 'imported' AS provenance,
       CAST(scraped_at AS STRING) AS scraped_at
FROM sampled WHERE sample_rank<={limit}
ORDER BY observed_on,domain,source,listing_id
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--per-source", type=int, default=50)
    parser.add_argument("--output", type=Path, default=Path("data/local/bakiano"))
    parser.add_argument("--bq", default=shutil.which("bq"))
    parser.add_argument("--execute", action="store_true", help="Otherwise only dry-run the query")
    parser.add_argument(
        "--resume-job", help="Recover an existing matching query result without querying again"
    )
    args = parser.parse_args()
    days = (args.end - args.start).days + 1
    if not 1 <= days <= 31 or not 1 <= args.per_source <= 100:
        parser.error("Require 1..31 dates and 1..100 products per source")
    if not args.bq:
        parser.error("Install/configure the BigQuery CLI for this opt-in export")
    if args.output.exists():
        parser.error("Output already exists; snapshots are immutable, choose a new path")
    query = query_for(args.project, args.start, args.end, args.per_source)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    base = [
        args.bq,
        "--project_id=" + args.project,
        "--format=json",
        "query",
        "--use_legacy_sql=false",
        f"--maximum_bytes_billed={MAX_BYTES}",
    ]
    if args.resume_job:
        if not re.fullmatch(r"delivery_local_sample_[a-f0-9]{32}", args.resume_job):
            parser.error("Invalid sample job ID")
        command = [args.bq, "--project_id=" + args.project, "--format=json"]
        job = args.resume_job
        info = subprocess.run(
            command + ["show", "--job=true", f"{args.project}:US.{job}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=90,
        )
        if info.returncode:
            raise RuntimeError("Could not inspect completed sample job")
        details = json.loads(info.stdout)
        config = details["configuration"]["query"]
        if config["query"].strip() != query.strip() or details["status"].get("errorResult"):
            raise ValueError("Job does not match this sample query")
        table = config["destinationTable"]
        if table["projectId"] != args.project or not all(
            re.fullmatch(r"[A-Za-z0-9_]+", table[key]) for key in ("datasetId", "tableId")
        ):
            raise ValueError("Invalid result table")
        result = subprocess.run(
            command
            + [
                "head",
                "-n",
                str(days * len(SOURCES) * args.per_source + 1),
                f"{args.project}:{table['datasetId']}.{table['tableId']}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=90,
        )
        if result.returncode:
            raise RuntimeError("Could not read completed sample results")
        rows = json.loads(result.stdout)
    else:
        rows = None
    dry = (
        subprocess.run(
            base + ["--dry_run"],
            input=query,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            env=env,
        )
        if rows is None
        else None
    )
    if dry and dry.returncode:
        raise RuntimeError("Read-only query dry run failed; check CLI authentication and access")
    print(
        json.dumps(
            {
                "dry_run": "passed",
                "requested_days": days,
                "max_rows": days * len(SOURCES) * args.per_source,
                "maximum_bytes_billed": MAX_BYTES,
            }
        )
    )
    if not args.execute and rows is None:
        return
    if rows is None:
        job = "delivery_local_sample_" + uuid4().hex
        print(json.dumps({"query_job_id": job}), flush=True)
        result = subprocess.run(
            base + [f"--max_rows={days * len(SOURCES) * args.per_source + 1}", "--job_id=" + job],
            input=query,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            env=env,
        )
        if result.returncode:
            raise RuntimeError("Read-only sample query failed; no dataset package was written")
        rows = json.loads(result.stdout)
    manifest = build_history(
        rows,
        args.output,
        args.start,
        args.end,
        SOURCES,
        per_source=args.per_source,
        metadata={
            "project": args.project,
            "job_id": job,
            "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "maximum_bytes_billed": MAX_BYTES,
            "observation_basis": "warehouse ingestion day; not live availability",
            "sampling": "stable first listing IDs per source across requested window",
            "privacy": "local private extract; do not commit source rows",
            "extracted_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(rows),
                "available_days": manifest["available_days"],
            }
        )
    )


if __name__ == "__main__":
    main()
