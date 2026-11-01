"""One semantic ranking interface over PostgreSQL or Vertex Vector Search.

Only embeddings and opaque scope hashes reach Vertex. Canonical facts are resolved
again through SQL after every search; the vector index is never an authority.
"""

import hashlib
import json
import math
import os
import re
from functools import lru_cache
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from delivery.db import Connection
from delivery.queue import Event

MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@lru_cache(maxsize=1)
def local_model() -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(
        MODEL, cache_dir=os.environ.get("DELIVERY_EMBEDDING_CACHE", "/tmp/mds-embedding"),
        local_files_only=True, threads=1,
    )


class LocalEmbedder:
    model = MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in local_model().embed(texts)]


class VectorBackend(Protocol):
    name: str

    def rank(
        self, facts: list[dict[str, Any]], vectors: list[list[float]], query: list[float],
        scope: dict[str, Any], model: str,
    ) -> list[int]: ...


def scope_hash(scope: dict[str, Any]) -> str:
    payload = json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class PgvectorBackend:
    name = "pgvector"

    def __init__(self, conn: Connection, event: Event) -> None:
        self.conn, self.event = conn, event

    def rank(self, facts: list[dict[str, Any]], vectors: list[list[float]], query: list[float],
             scope: dict[str, Any], model: str) -> list[int]:
        event = self.event
        ticket = (event.id, event.token, event.attempts)
        self.conn.execute("SELECT public.agent_semantic_cache(%s,%s,%s,%s,%s)",
                          (*ticket, model, Jsonb([
                              {"fact_id": f["fact_id"], "embedding": v}
                              for f, v in zip(facts, vectors, strict=True)
                          ])))
        row = self.conn.execute(
            "SELECT public.agent_semantic_neighbors(%s,%s,%s,%s,%s,%s) AS ids",
            (*ticket, model, Jsonb(query), len(facts)),
        ).fetchone()
        assert row
        return list(row["ids"])


class VertexVectorBackend:
    name = "vertex"

    def __init__(self, *, index: str, endpoint: str, deployed_index: str,
                 public_domain: str, session: Any = None) -> None:
        pattern = r"projects/[0-9]+/locations/([a-z0-9-]+)/"
        if (not re.fullmatch(pattern + r"indexes/[0-9]+", index)
                or not re.fullmatch(pattern + r"indexEndpoints/[0-9]+", endpoint)
                or index.split("/")[:4] != endpoint.split("/")[:4]
                or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,127}", deployed_index)
                or not re.fullmatch(r"[a-z0-9.-]+\.vdb\.vertexai\.goog", public_domain)):
            raise ValueError("Invalid configured Vertex Vector Search endpoints")
        self.index, self.endpoint, self.deployed_index = index, endpoint, deployed_index
        self.public_domain, self.session = public_domain, session

    def _session(self) -> Any:
        if self.session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            self.session = AuthorizedSession(credentials)
        return self.session

    def rank(self, facts: list[dict[str, Any]], vectors: list[list[float]], query: list[float],
             scope: dict[str, Any], model: str) -> list[int]:
        # Scope is obtained from the authenticated runtime, never natural-language input.
        restrictions = [{"namespace": "scope", "allowList": [scope_hash(scope)]},
                        {"namespace": "model", "allowList": [scope_hash({"model": model})]}]
        region = self.index.split("/")[3]
        data = {"datapoints": [
            {"datapointId": f"{scope_hash({'model': model})[:12]}-{f['fact_id']}",
             "featureVector": vector, "restricts": restrictions,
             "numericRestricts": [{"namespace": "expires_sim", "valueInt": str(f["expires_sim"])}]}
            for f, vector in zip(facts, vectors, strict=True)
        ]}
        session = self._session()
        response = session.post(
            f"https://{region}-aiplatform.googleapis.com/v1/{self.index}:upsertDatapoints",
            json=data, timeout=10,
        )
        response.raise_for_status()
        response = session.post(
            f"https://{self.public_domain}/v1/{self.endpoint}:findNeighbors",
            json={"deployedIndexId": self.deployed_index, "queries": [{
                "datapoint": {"featureVector": query, "restricts": restrictions},
                "neighborCount": len(facts),
            }], "returnFullDatapoint": False}, timeout=10,
        )
        response.raise_for_status()
        neighbors = response.json().get("nearestNeighbors", [])
        raw = neighbors[0].get("neighbors", []) if neighbors else []
        prefix = scope_hash({"model": model})[:12] + "-"
        result = []
        for hit in raw[:8]:
            identifier = hit.get("datapoint", {}).get("datapointId", "")
            if identifier.startswith(prefix) and identifier[len(prefix):].isdigit():
                result.append(int(identifier[len(prefix):]))
        return result


def backend(conn: Connection, event: Event) -> VectorBackend:
    selected = os.environ.get("DELIVERY_MEMORY_BACKEND", "pgvector")
    if selected == "pgvector":
        return PgvectorBackend(conn, event)
    if selected != "vertex":
        raise ValueError("Unknown semantic memory backend")
    return VertexVectorBackend(
        index=os.environ.get("DELIVERY_VECTOR_INDEX", ""),
        endpoint=os.environ.get("DELIVERY_VECTOR_ENDPOINT", ""),
        deployed_index=os.environ.get("DELIVERY_VECTOR_DEPLOYED_INDEX", ""),
        public_domain=os.environ.get("DELIVERY_VECTOR_PUBLIC_DOMAIN", ""),
    )


def rank_facts(
    facts: list[dict[str, Any]], query: str, scope: dict[str, Any], index: VectorBackend,
    embedder: Embedder | None = None,
) -> tuple[list[int], dict[str, Any]]:
    if (not isinstance(query, str) or not query.strip()
            or len(query.encode("utf-8")) > 512 or len(facts) > 8):
        raise ValueError("Semantic recall requires a bounded query and canonical candidates")
    embedder = embedder or LocalEmbedder()
    texts = [json.dumps({"kind": f["kind"], "body": f["body"]}, sort_keys=True) for f in facts]
    if not facts:
        return [], {"backend": index.name, "model": embedder.model, "candidate_count": 0}
    vectors = embedder.embed([query, *texts])
    if len(vectors) != len(facts) + 1 or any(
        len(v) != DIMENSIONS or not all(math.isfinite(x) for x in v)
        or not any(x != 0 for x in v) for v in vectors
    ):
        raise ValueError("Invalid semantic embedding output")
    ranked = index.rank(facts, vectors[1:], vectors[0], scope, embedder.model)
    allowed = {int(f["fact_id"]) for f in facts}
    ids = list(dict.fromkeys(i for i in ranked if i in allowed))[:8]
    return ids, {"backend": index.name, "model": embedder.model,
                 "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                 "candidate_count": len(facts), "ranked_fact_ids": ids,
                 "embedding_paid_calls": 0}
