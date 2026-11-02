"""Public, synthetic memory documentation built from runtime contracts.

Never reads a run, environment configuration, database or cloud service.
"""
from typing import Any

from delivery.agent_specs import RoleSpec
from delivery.memory_profiles import MemoryProfile, project_memory
from delivery.semantic_memory import DIMENSIONS, MODEL
from delivery.typed_memory import CONTRACTS, validate_fact

SOURCES = [
    "src/delivery/memory_reference.py",
    "src/delivery/typed_memory.py",
    "src/delivery/memory_profiles.py",
    "src/delivery/semantic_memory.py",
    "src/delivery/agent_runtime.py",
    "src/delivery/adk_restaurant.py",
    "sql/migrations/015_typed_memory.sql",
    "sql/migrations/024_agent_memory_modes.sql",
    "sql/migrations/031_semantic_memory.sql",
    "infra/production/live.tf",
    "infra/production/vector.tf",
    "tests/test_semantic_memory.py",
    "evals/memory/recall.json",
]
SAMPLES: dict[str, dict[str, Any]] = {
    "inventory.reservation": {"status": "reserved"},
    "inventory.shipment": {"status": "delayed", "expected_sim": 900},
    "fulfillment.progress": {"status": "picked"},
    "delivery.progress": {"status": "assigned", "attempt": 1, "courier": "demo-courier"},
    "courier.commitment": {"status": "accepted", "attempt": 1},
    "recovery.verdict": {"verdict": "approved", "attempt": 1,
                         "reason": "A replacement can arrive before the deadline.",
                         "remaining_seconds": 600},
    "household.order": {"status": "calling", "action": "calling"},
    "restaurant.order": {"status": "cooking", "action": "ingredient_received"},
    "market.request": {"ingredient": "tomato", "quantity": 500.0, "unit": "g",
                       "outcome": "supplier_reserved"},
}
PROFILE_NOTES = {
    "none": "Returns an empty list. Writes and the audit ledger still exist.",
    "text": "A bounded string with scope, facts and provenance. It is not a text file.",
    "json": "A JSON object separates shared scope, fact bodies and provenance.",
    "typed": "A list of complete typed records, including scope and provenance.",
    "semantic": "Ranks the permitted candidates by meaning, then returns typed records. "
                "This one-record example shows the shape, not a measured search result.",
}


def memory_reference(role: RoleSpec) -> dict[str, Any]:
    profile = MemoryProfile()
    schema = profile.model_json_schema()
    contracts = []
    for kind, (owner, subject, topics, body_type) in CONTRACTS.items():
        if owner != role.name:
            continue
        body = validate_fact(kind, SAMPLES[kind], owner, topics[0])
        context_type = "shipment" if subject == "shipment" else "order"
        context_id = "demo-shipment" if subject == "shipment" else "demo-order"
        record = {
            "fact_id": 42, "run_id": "00000000-0000-0000-0000-000000000001",
            "store": "demo-store", "owner_role": owner,
            "context_type": context_type, "context_id": context_id,
            "kind": kind, "subject": "demo-request" if subject == "request" else context_id,
            "version": 1, "body": body, "observed_sim": 120,
            "expires_sim": 120 + profile.ttl_seconds, "event_id": 17, "previous_id": None,
        }
        contracts.append({
            "kind": kind, "topics": list(topics), "subject": subject,
            "body_schema": body_type.model_json_schema(), "record": record,
            "projections": {
                mode: project_memory(MemoryProfile(mode=mode), [record])
                for mode in schema["properties"]["mode"]["enum"]
            },
        })
    return {
        "persistent": bool(contracts),
        "applicability": (
            "The scoped worker writes these observations. Restaurant ADK recall passes "
            "the selected projection into its tool response. Deterministic workers keep "
            "canonical facts for decisions and audit; a memory profile does not add a model."
            if contracts else
            "This complaint classifier has no persistent memory contract or memory tools. "
            "Its ADK session is created per complaint. Request/result receipts prevent "
            "repeat billing, but are not semantic recall. Chaos turns receive only the "
            "affected order facts."
        ),
        "format": "PostgreSQL rows with a JSONB body",
        "format_note": "This is not a CSV, chat transcript or file per agent. A typed "
                       "observation records what happened; order and stock tables still "
                       "decide what is true now.",
        "contracts": contracts,
        "profile_defaults": profile.model_dump(),
        "profile_schema": schema,
        "profile_notes": PROFILE_NOTES,
        "manifest_profile": role.memory.model_dump() if role.memory else None,
        "capacity": {
            "memory_entries": role.limits.memory_entries,
            "memory_bytes": role.limits.memory_bytes,
            "tool_calls_per_event": role.limits.tool_calls_per_event,
        },
        "fields": [
            {"title": "Scope", "keys": ["run_id", "store", "owner_role", "context_type",
                                      "context_id", "subject"],
             "note": "SQL derives these from the authenticated role and its leased event. "
                     "The agent cannot choose another order or namespace."},
            {"title": "Observation", "keys": ["kind", "body"],
             "note": "A role-specific schema validates the body in Python and SQL. "
                     "Unknown fields are rejected; observations grant no authority."},
            {"title": "History", "keys": ["fact_id", "version", "event_id", "observed_sim",
                                        "expires_sim", "previous_id"],
             "note": "The database assigns identity, provenance and revision. Times are "
                     "simulation seconds, not wall-clock timestamps. fact_id is the "
                     "recall name for the SQL row's id."},
        ],
        "recall_path": [
            ["Leased event", "Authenticated role + current order or shipment."],
            ["SQL scope gate", "Latest, unexpired facts in that exact scope."],
            ["Optional ranking", "Semantic mode ranks only this small authorized set."],
            ["SQL recheck", "Semantic results are checked again for "
             "scope, lease, TTL and revision."],
            ["Agent input", "The selected representation reaches the policy or ADK tool response."],
        ],
        "semantic": {
            "model": MODEL, "dimensions": DIMENSIONS, "query_bytes": 512,
            "paid_embedding_calls": 0,
            "note": "The packaged local embedding model runs on CPU without downloading "
                    "weights during a turn. Infrastructure still costs money. Ranking "
                    "does not search all customer history or bypass order boundaries.",
        },
        "storage": {
            "local": {
                "title": "Local PostgreSQL",
                "status": "Implemented path; no live deployment check",
                "nodes": [
                    ["Worker", "Role-bound tools; no direct table access"],
                    ["PostgreSQL volume", "agent_memory_facts: typed columns + JSONB body"],
                    ["Optional pgvector", "agent_semantic_vectors: JSONB embedding arrays, "
                     "cast to vector for cosine search"],
                ],
                "details": [
                    "Docker Compose keeps PostgreSQL data in the postgres-data volume.",
                    "The agent_memory_current view picks the latest revision before "
                    "expiry filtering. Expiring a new revision never revives an old one.",
                    "The vector cache is keyed by fact_id and model. Canonical facts "
                    "remain in SQL and are rechecked after ranking.",
                ],
            },
            "gcp": {
                "title": "Optional Google Cloud live path",
                "status": "Terraform capability, not a claim that services are running",
                "nodes": [
                    ["Cloud Run worker", "Role service account + scoped database login"],
                    ["Cloud SQL / PostgreSQL 17", "Same canonical facts, schemas and audit ledger"],
                    ["Optional Vertex Vector Search", "384-number vectors + fact IDs + scope/model "
                     "hashes + expiry metadata; no raw fact text"],
                ],
                "details": [
                    "Live storage requires active + enable_live. Service startup also "
                    "requires live_ready after migrations, scoped logins and secret versions.",
                    "Vertex additionally requires enable_vector_search. The worker uses "
                    "Application Default Credentials; IAM grants index update/query only "
                    "to the configured api, restaurant and dispatcher identities.",
                    "The endpoint uses public networking with authenticated API calls. "
                    "Hashes are scope filters, not encryption. Embeddings are derived data.",
                    "Cloud SQL and the one-replica Vertex deployment have idle costs. "
                    "The public replay does not need live memory. active=false removes "
                    "these resources; this reference never provisions them.",
                    "The current lab Terraform disables SQL backups and deletion protection. "
                    "TTL is not deletion; teardown can remove retained history. No automatic "
                    "Vertex TTL deletion or archival pipeline is implemented here.",
                ],
            },
        },
        "rules": [
            ["Scope", "Run + entity/store + owner role + order/shipment context; supplier "
             "requests and courier assignment attempts add subject checks. No cross-order "
             "or cross-role recall, including repeat-customer complaints."],
            ["Write", "The body is at most 2,048 SQL-serialized bytes. Write TTL is 1 to "
             "86,400 simulation seconds; an explicit profile clamps it further. "
             "Same source event/type/subject is idempotent; conflicting content is rejected."],
            ["Recall", "Explicit profiles cap complete output at the selected fact and "
             "UTF-8 byte limits. Oversized facts are omitted whole, never truncated. "
             "Unconfigured legacy recall allows up to 16 facts and 8 KiB."],
            ["Expiry", "Only the latest unexpired revision can return. TTL hides recall "
             "without deleting audit history. mode=none also leaves writes and audit intact."],
            ["Tool budget", "Each recall consumes a tool slot. Semantic recall consumes "
             "two fenced reads. Exhausted budget, stale lease or invalid embedding fails closed."],
            ["Commit & audit", "Trusted workers commit memory, decision receipt, outgoing "
             "events and ACK atomically. Receipts record fact IDs and versions; semantic "
             "receipts add backend, model, query hash and returned IDs."],
            ["Trust limit", "Database grants and fixed functions enforce access. The "
             "Python host and operator are trusted; this is not an operating-system "
             "sandbox or proof that every authorized observation is true."],
        ],
        "lifecycle": [
            ["Written", "v1 records a validated observation."],
            ["Revised", "v2 replaces it for recall; v1 remains in audit."],
            ["Expired", "v2 disappears from recall; v1 does not return."],
        ],
        "evidence": [
            "Three checked-in recall cases cover repeated reservation, stock refusal and "
            "expiry. They compare retained evidence with mode=none, within one order.",
            "Tests exercise real local embeddings and pgvector, cross-order/role "
            "isolation, expiry and stale results. Vertex request/auth/filter behavior "
            "is tested with a mocked service; this is not a live GCP quality benchmark.",
            "No memory-specific production pass rate, latency or monetary cost receipt "
            "is published here. Zero paid embedding calls does not mean zero hosting cost.",
        ],
        "sources": SOURCES,
    }
