# Scoped semantic recall

Select **Semantic recall** in the existing agent memory control. Install the
`memory` optional dependency when running without Docker. The Docker build pins
FastEmbed and downloads BGE-small-en-v1.5 (384 dimensions) into `/opt/mds-models`.
Runtime loading is local-only: no download, paid embedding call or API key.

`DELIVERY_MEMORY_BACKEND=pgvector` uses exact cosine search over the small authorized
set, through PostgreSQL security-definer functions. The Compose Postgres image
includes PostGIS and pgvector. Embeddings are an immutable derived cache, stored as
JSON and cast to pgvector during the bounded search. No global search precedes
authorization.

`DELIVERY_MEMORY_BACKEND=vertex` selects Vertex Vector Search. Configure
`DELIVERY_VECTOR_INDEX`, `DELIVERY_VECTOR_ENDPOINT`,
`DELIVERY_VECTOR_DEPLOYED_INDEX` and `DELIVERY_VECTOR_PUBLIC_DOMAIN`. Resource paths
must use project numbers and one matching region. ADC authenticates the requests.
Only vectors, opaque scope/model hashes, fact IDs and expiry metadata leave SQL;
canonical text remains in PostgreSQL. Streaming index updates are eventually
consistent, so a new observation may not be immediately returned.

Both backends rank the same canonical candidates. After searching, the runtime
performs a second budgeted, lease-fenced SQL read and intersects the result with
current authorized facts. Foreign IDs, obsolete versions, expired facts and lost
leases cannot become context. Query hashes and returned fact IDs join the existing
memory audit. Semantic recall consumes two read slots; existing fact/byte limits
remain unchanged. An unavailable backend fails closed rather than changing scope.
The ADK restaurant path uses its existing turn nonce for both reads; the final
SQL function updates the actual turn context and records a `memory.semantic`
tool receipt. The test exercises this path with a real pgvector query.

The eval cohort in `evals/memory/recall.json` measures repeated questions within
one order, comparing retained facts against the `none` profile. Tests use the real
local embedding model and pgvector, test a paraphrase against an unrelated text,
and assert order/role/lease/TTL boundaries. Many roles currently have just one
current fact per order: these tests demonstrate useful retained evidence and
semantic matching, **not** superiority over typed recall or a live-model benchmark.
Cross-order repeat-customer history is deliberately outside the existing scope.

The vector cache is derived data. PostgreSQL deletes its entries when canonical
facts are purged. Vertex datapoints must be removed by the deployment's retention
job when canonical records are purged; expiry is always enforced at SQL hydration,
even before that physical cleanup. Do not interpret vector-index membership as
permission or as an audit source.
