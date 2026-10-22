# Local Bakiano sample and execution policy

Decision: 2026-10-23. Build and polish locally. GCP portability remains optional
future work, not a prerequisite or an always-on demo environment.

## Current frozen sample

Requested ten daily buckets: **2026-10-14 through 2026-10-23 inclusive**. Today minus
ten through today would contain eleven dates (October 13-23); ten dates including
today begin October 14.

The local private package contains **2,008 product observations** across nine
available dates, October 14-22. October 23 had no matching observations at extraction
time and remains explicitly missing. This is a frozen extraction, not a completeness
claim about later warehouse updates. No scheduled refresh or live query is required.

Sources: Gama, Central Madeirense and Plazas (supermarkets); Daka and EPA (retail).
Select at most 50 stable source listing identities per vendor across the whole
window, rather than a different random assortment every day. Individual days can
contain fewer than 50 observations per vendor. This sample is not representative
of the full assortment, market or sales. Stock, shipments and demand remain simulated.

Only vendors confirmed as USD in Bakiano's registry are selected. Preserve source
listing IDs, observed prices rounded to cents, categories/URLs where available and
missing values. The daily bucket uses warehouse ingestion date; collection timestamps
are retained in the manifest. A listing is not proof of real store availability.

Files live in ignored `data/local/bakiano/`: manifest plus one catalogue per available
day. Date entries include per-source counts and content hashes. Missing days have no
catalogue file. Never forward-fill prices or relabel old products as new observations.
The public [coverage receipt](bakiano-sample-coverage.json) contains counts only.

## Use entirely offline

The local app exposes date selection at `/lab`. Each fictional store binds to one
source catalogue; product observations remain separate from generated stock. Missing
dates cannot start runs. The manifest and chosen snapshot hash are checked before use.

```sh
docker compose up -d --build --wait
docker compose exec -T app delivery lab-demo --sample-date 2026-10-22
```

Compose mounts `data/local/` read-only and excludes it from the image build context.
The private sample is also excluded from Git. The committed synthetic fixture runs
when no private package exists. Default Compose services do not receive `.env`
credentials, remote model calls are disabled, and host settings do not implicitly
load `.env`. Explicit process environment settings remain an opt-in developer interface.

No local runtime command reads Bakiano's warehouse, starts GCP infrastructure or
refreshes the sample. Existing provider adapters are retained as optional code, not
activated by ordinary local startup.

## Optional one-time acquisition

The exporter is a separate opt-in preparation tool. It needs an authenticated
BigQuery CLI only on the machine fetching the sample, not in the application image.
It reads only selected catalogue columns for five sources and explicit date
partitions. It never modifies Bakiano tables, triggers collectors or deploys services.
The query is dry-run first and capped at 1 GiB billed bytes; LIMIT alone is not a
scan-cost control. Actual extraction processed 202,235,905 bytes, below the cap.

```sh
python scripts/export_bakiano_sample.py --project PROJECT_ID --start 2026-10-14 --end 2026-10-23
python scripts/export_bakiano_sample.py --project PROJECT_ID --start 2026-10-14 --end 2026-10-23 --execute
```

The first command only validates the query. Existing output directories are never
overwritten. For a later refresh, use `--output` with a new directory, verify its
manifest, then deliberately select/install that package. For a failed result download,
`--resume-job` retrieves a matching completed query's temporary result table without
executing the query again, while it remains available. The CLI prints its job ID
before downloading and forces UTF-8 to preserve Spanish names on Windows.

Keep extraction credentials outside datasets, prompts, event payloads and traces.
Only the root extraction process handles them; delegated code/documentation work
uses synthetic records and no private sample access.
