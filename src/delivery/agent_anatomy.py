"""Read-only agent explanations derived from the same contracts used at runtime.

No database, environment secrets, provider clients or live model calls. Evidence
is dated, checked-in evidence, not a claim that the current checkout was evaluated.
"""

import ast
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

from google.protobuf.json_format import MessageToDict

from delivery.adk_contracts import JevRouting, restaurant_template
from delivery.agent_specs import load_role
from delivery.config import Settings
from delivery.memory_profiles import MemoryProfile
from delivery.role_manifest import manifest_names

ROOT = Path(__file__).resolve().parents[2]
PARTS = (
    ("mission", "Role & mission", "Cab", "agent-implementation"),
    ("persona", "SOUL & persona", "Face", "agent-implementation"),
    ("tools", "Tools", "Arms", "agent-runtime"),
    ("memory", "Memory & scope", "Storage tank", "memory"),
    ("policy", "Policy & guardrails", "Safety cage", "agent-runtime"),
    ("limits", "Limits & budget", "Fuel gauge", "agent-runtime"),
    ("model", "Model & routing", "Engine", "adk-restaurant"),
    ("protocols", "A2A & MCP", "Antenna", "a2a"),
    ("events", "Events in & out", "Intake / exhaust", "delivery-flow"),
    ("evals", "Evals & results", "Inspection sticker", "evals"),
    ("environment", "Runtime environment", "Wheels", "gcp-components"),
)
EVAL_ARMS = {
    "dispatcher": ("adk-chaos-dispatcher",),
    "restaurant": ("adk-offline-restaurant", "adk-chaos-restaurant"),
    "customer_service": ("adk-offline-customer", "adk-customer-policy", "adk-chaos-customer"),
}


def read_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def source_paths() -> list[str]:
    paths = [
        "config/agents/role.schema.json",
        "src/delivery/agent_anatomy.py",
        "src/delivery/agent_specs.py",
        "src/delivery/role_manifest.py",
        "src/delivery/agent_runtime.py",
        "src/delivery/agent_access.py",
        "src/delivery/adk_contracts.py",
        "src/delivery/adk_customer.py",
        "src/delivery/customer_service.py",
        "src/delivery/config.py",
        "src/delivery/chaos_agents.py",
        "src/delivery/queue.py",
        "src/delivery/memory_profiles.py",
        "src/delivery/semantic_memory.py",
        "src/delivery/jev_routing.py",
        "src/delivery/a2a_server.py",
        "src/delivery/mcp_server.py",
        "src/delivery/fleet_policy.py",
        "src/delivery/environment.py",
        "src/delivery/madrid_city.py",
        "src/delivery/dark_store.py",
        "src/delivery/store_layout.py",
        "compose.yaml",
        "docs/evidence/main-consolidation.json",
        "docs/evidence/heldout-release.json",
        "docs/evidence/a2a-chaos-local.json",
    ]
    for name in manifest_names():
        paths += [f"config/agents/{name}/role.json", f"config/agents/{name}/SOUL.md"]
    paths += [
        "config/agents/restaurant-adk/" + name
        for name in ("PROMPT.md", "SOUL-speed.md", "SOUL-cost.md")
    ]
    return sorted(paths)


def input_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in source_paths():
        digest.update(path.encode() + b"\0" + (ROOT / path).read_bytes())
    return digest.hexdigest()


def anatomy_data() -> dict[str, Any]:
    from delivery.a2a_server import agent_card
    from delivery.chaos_agents import RecoveryTurn
    from delivery.customer_service import MAX_OUTPUT, RESERVED_TOKENS, refund_policy

    release = read_json("docs/evidence/heldout-release.json")
    verified = read_json("docs/evidence/main-consolidation.json")
    chaos = read_json("docs/evidence/a2a-chaos-local.json")["live_demo"]
    brain, _ = restaurant_template()
    profile = MemoryProfile()
    mcp_tree = ast.parse((ROOT / "src/delivery/mcp_server.py").read_text(encoding="utf-8"))
    mcp_tools = [
        node.name
        for node in ast.walk(mcp_tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool"
            for d in node.decorator_list
        )
    ]
    agents: list[dict[str, Any]] = []
    for name in manifest_names():
        if name == "judge-gcp":
            continue
        role = load_role(name)
        manifest = f"config/agents/{name}/role.json"
        soul = f"config/agents/{name}/SOUL.md"
        accepted = role.service_events.get("accepts", role.accepts)
        emitted = role.service_events.get("emits", role.emits)
        card_name = "restaurant-kitchen" if name == "restaurant" else name
        card = (
            MessageToDict(agent_card(card_name, base_url="http://localhost:8010", live=False))
            if name in {*EVAL_ARMS, "inventory", "fulfillment"}
            else None
        )
        model = "No model: deterministic Python/SQL policy."
        model_details = ["Routine decisions do not require inference or a provider connection."]
        model_numbers: dict[str, Any] = {"Routine model calls": 0}
        if name == "restaurant":
            model = (
                "Deterministic by default; selectable ADK uses an offline fixture or opt-in Vertex."
            )
            model_details = [
                "The blueprint chooses the restaurant brain. Offline ADK runs the real Runner "
                "with scripted function calls; it does not demonstrate live model intelligence.",
                "Jev-first routing can choose direct tool execution (no Gemini call), or "
                "escalate a reasoning decision to the operator-approved Gemini profile.",
                "No live model is silently selected when a provider is disabled.",
            ]
            routing = JevRouting()
            model_numbers = {
                "ADK calls / event": brain.model_calls_per_event,
                "ADK calls / run": brain.model_calls_per_run,
                "Output tokens / call": brain.output_tokens,
                "Jev confidence threshold": routing.confidence_threshold,
                "Jev margin threshold": routing.margin_threshold,
            }
        elif name == "customer_service":
            model = "ADK classifies a complaint; fixed policy decides money and escalation."
            model_details = [
                "Disabled by default: unresolved requests are queued for operator review.",
                "Offline runs use a scripted ADK fixture. Opt-in Gemini/Vertex uses the "
                "configured model; the checked-in default is "
                f"{Settings.model_fields['llm_model'].default}.",
                "The classification turn has no tools or agent transfers. Chaos recovery "
                "uses a separate scoped tool turn.",
            ]
            model_numbers = {
                "Classification calls / complaint": 1,
                "Reserved tokens / complaint": RESERVED_TOKENS,
                "Maximum output tokens": MAX_OUTPUT,
            }
        elif name == "dispatcher":
            model_details.append(
                "Chaos recovery uses an ADK turn to choose an action; "
                "the normal economic matching algorithm executes reassignment."
            )
        elif name == "judge":
            variant = load_role("judge-gcp")
            model_details.append(
                "The optional judge-gcp profile asks a bounded remote judge; "
                "its verdict cannot execute a delivery."
            )
            model_numbers.update(
                {
                    "Optional GCP calls / run": variant.limits.model_calls,
                    "Optional GCP token cap": variant.limits.model_tokens,
                }
            )

        tool_details = [f"{tool}: {role.tool_descriptions[tool]}" for tool in role.tools]
        tool_details += [
            f"{tool} (Chaos): {inspect.getdoc(getattr(RecoveryTurn, tool))}"
            for tool in role.recovery_tools
        ]
        if name == "restaurant":
            tool_details.insert(
                0,
                "The manifest contains the capability ceiling. A deterministic "
                "profile and a granular ADK profile select different subsets.",
            )
        if name == "customer_service":
            tool_details.insert(
                0,
                "Complaint classification has zero business tools. The tools "
                "below belong only to the separate Chaos recovery turn.",
            )
        policy_details = [
            "role.json grants capabilities; SOUL, messages and recalled text cannot expand them.",
            "SQL and fixed tool implementations enforce scope, lease fencing and business "
            "invariants. A manifest cannot create a new executable tool.",
            *role.design_decisions,
            *["Known limit: " + limit for limit in role.known_limits],
        ]
        policy_numbers: dict[str, Any] = {"Unrestricted SQL / shell tools": 0}
        if name == "customer_service":
            policy_numbers["Automatic overdue refund maximum (EUR)"] = refund_policy(100, True)[1]
            policy_numbers["Approval required above (EUR)"] = 100
            policy_details.append(
                "Refund requests above €100 await approval. Otherwise an "
                "overdue order can receive at most €5; model advice cannot "
                "override that policy."
            )
        limits_numbers = {
            key.replace("_", " "): value for key, value in role.limits.model_dump().items()
        }
        if name == "customer_service":
            limits_numbers = {
                "Default calls / run": Settings.model_fields["llm_max_calls"].default,
                "Default reserved tokens / run": Settings.model_fields["llm_max_tokens"].default,
                "Default run budget (USD)": Settings.model_fields["llm_budget_usd"].default,
            }
        eval_rows = [
            {"arm": arm, **release["summary"][arm]}
            for arm in EVAL_ARMS.get(name, ())
            if arm in release["summary"]
        ]
        eval_details = [
            f"Recorded {release['created_at']} for {release['source_revision']}. "
            f"Verified source commit: {release['verified_commit'][:12]}.",
            "pass^k is the share of cases passing every attempt. The bootstrap resamples "
            "cases; [1, 1] on an all-pass fixture is not certainty about unseen workloads.",
            "Scripted offline contract and policy checks, not live-model quality, inference "
            "cost or production latency. This is historical evidence, not a live check.",
        ]
        if not eval_rows:
            eval_details.insert(
                0,
                "No per-role held-out ADK result is recorded for this "
                "deterministic role. Its runtime and workflow are covered "
                "by the Python suite and deterministic role scenarios.",
            )
        memory_details = [
            "Typed observations are scoped by run, entity/store, owner role, context type "
            "and order. Expiry, fact revisions and provenance stay authoritative in SQL.",
            "Selectable profiles: none, text, JSON, typed or semantic. Semantic recall "
            "uses local pgvector or optional Vertex Vector Search behind the same scope checks.",
            "These are profile defaults. The frozen run definition can select stricter "
            "settings; this page does not expose private run memory.",
        ]
        if name == "customer_service":
            memory_details = [
                "Complaint ADK sessions are ephemeral and do not share memory. "
                "Durable request/result receipts prevent repeat billing. Chaos "
                "turns receive only the affected order's facts.",
                "The shared semantic-memory layer has isolation evals; it is "
                "not wired into this complaint classifier as persistent recall.",
            ]
        panels: dict[str, dict[str, Any]] = {
            "mission": dict(
                summary=role.mission,
                details=[role.why_it_exists, *role.design_decisions],
                numbers={"Role templates": 1},
                sources=[manifest],
            ),
            "persona": dict(
                summary="SOUL describes behavior; it never grants permissions.",
                details=[role.soul.strip()],
                numbers={"Permission grants from SOUL": 0},
                sources=[soul],
            ),
            "tools": dict(
                summary="Each tool performs one bounded action inside this role's scope.",
                details=tool_details or ["No business tools in this profile."],
                numbers={
                    "Manifest tool ceiling": len(role.tools),
                    "Chaos tools": len(role.recovery_tools),
                },
                sources=[manifest, "src/delivery/agent_runtime.py", "src/delivery/chaos_agents.py"],
            ),
            "memory": dict(
                summary="Recall is scoped evidence, never shared unrestricted chat.",
                details=memory_details,
                numbers=(
                    {"Persistent classifier recall": 0}
                    if name == "customer_service"
                    else profile.model_dump()
                ),
                sources=["src/delivery/memory_profiles.py", "src/delivery/semantic_memory.py"],
            ),
            "policy": dict(
                summary="The model may propose; scoped code validates every effect.",
                details=policy_details,
                numbers=policy_numbers,
                sources=[
                    manifest,
                    "src/delivery/agent_specs.py",
                    "src/delivery/customer_service.py",
                ],
            ),
            "limits": dict(
                summary="Work stops when the reserved event, tool or model budget runs out.",
                details=[
                    "Shown are checked-in defaults, not a running agent's remaining "
                    "balance. Supply dispatch can use a bounded run profile; ADK "
                    "model budgets are separate from deterministic tool budgets.",
                    *role.known_limits,
                ],
                numbers=limits_numbers,
                sources=[manifest, "src/delivery/agent_access.py", "src/delivery/config.py"],
            ),
            "model": dict(
                summary=model,
                details=model_details,
                numbers=model_numbers,
                sources=[
                    "src/delivery/adk_contracts.py",
                    "src/delivery/jev_routing.py",
                    "src/delivery/adk_customer.py",
                ],
            ),
            "protocols": dict(
                summary=(
                    "A2A advertises a typed command boundary for this role."
                    if card
                    else "This role cooperates through the durable queue; it has no A2A server."
                ),
                details=[
                    (
                        "The card is produced by the same factory as the server. Restaurant "
                        "card shown here is a template; running identities have individual cards."
                        if card
                        else "A2A connects dispatcher, restaurant, customer service, "
                        "inventory and fulfillment; "
                        "other roles retain scoped event handoffs."
                    ),
                    "MCP is a separate read-only simulation server for external agents: "
                    + ", ".join(mcp_tools)
                    + ". "
                    "It does not grant these agents write capabilities.",
                    "Local A2A is loopback-only. The optional live tier requires "
                    "audience-bound Google ID tokens.",
                ],
                numbers={
                    "A2A cards for this template": int(card is not None),
                    "Read-only MCP tools": len(mcp_tools),
                },
                sources=["src/delivery/a2a_server.py", "src/delivery/mcp_server.py"],
                card=card,
            ),
            "events": dict(
                summary="Typed inputs and outputs make handoffs inspectable and retryable.",
                details=[
                    "Incoming: " + ", ".join(accepted),
                    "Outgoing: " + ", ".join(emitted),
                    "Delivery is at least once. Leases and transactional outboxes "
                    "protect database effects; external inference is not exactly once.",
                ],
                numbers={"Input topics": len(accepted), "Output topics": len(emitted)},
                sources=[manifest, "src/delivery/queue.py"],
            ),
            "evals": dict(
                summary=(
                    "Recorded held-out results cover this role's ADK contracts."
                    if eval_rows
                    else "Deterministic workflow coverage; no role-specific "
                    "held-out ADK score is recorded."
                ),
                details=eval_details,
                numbers={"Recorded Python suite passes": verified["checks"]["pytest"]["passed"]},
                results=eval_rows,
                sources=[
                    "docs/evidence/heldout-release.json",
                    "docs/evidence/main-consolidation.json",
                ],
            ),
            "environment": dict(
                summary="Runs locally in the Python service with scoped PostgreSQL state.",
                details=[
                    "Compose supplies the application, PostgreSQL and Redis. "
                    "The default demonstration makes no paid model calls.",
                    "Public Cloud Run replay plays recorded frames; it does "
                    "not run these agents. The optional private live tier is "
                    "disabled and not production-qualified.",
                    "Private SQL controller provisioning and cloud qualification "
                    "remain unfinished. This page starts no services.",
                ],
                numbers={"Paid calls made by this page": 0},
                sources=["compose.yaml"],
            ),
        }
        if name in {"inventory", "fulfillment", "dispatcher", "courier"}:
            from delivery.store_layout import StoreLayoutConfig

            layout = StoreLayoutConfig()
            panels["environment"].update(
                summary=("Works across Madrid streets and a physical dark store."
                         if name in {"dispatcher","courier"} else
                         "Works in the inventory lab or inside a Madrid dark store."),
                details=panels["environment"]["details"] + [
                    "DarkStore shares MadridCity's clock, durable events and order IDs.",
                    "Inventory reserves existing catalogue stock. Fulfillment walks aisles, "
                    "picks real shelf units, packs and carries the basket to the dock.",
                    "Dispatch starts only after the dock handoff. Robot recovery requires "
                    "a replacement picker to reach the stranded basket.",
                    "Store motion is a deterministic grid simulation, not robotics physics.",
                ],
                numbers={"Default aisles":layout.aisles,"Default pickers":layout.picker_count,
                         "Walking metres per second":layout.speed_mps,
                         "Seconds per pick":layout.pick_seconds,
                         "Packing seconds":layout.pack_seconds,"Paid model calls":0},
                sources=["src/delivery/environment.py","src/delivery/madrid_city.py",
                         "src/delivery/dark_store.py","src/delivery/store_layout.py"],
            )
        if name in {"inventory","fulfillment","dispatcher","courier"}:
            panels["environment"]["environments"] = {
                "dark_store": {
                    "label":"Dark store",
                    "summary":"Physical shelves, aisle paths, packing and a courier loading dock.",
                    "details":panels["environment"]["details"],
                    "numbers":panels["environment"]["numbers"],
                },
                "madrid_city": {
                    "label":"Madrid city",
                    "summary":"Madrid road routes connect store docks with customer doorsteps.",
                    "details":["The city clock advances courier movement on the OSM road network.",
                               "A store order becomes dispatchable only after physical packing "
                               "and dock arrival. No model is needed for movement."],
                    "numbers":{"City-only tick seconds":60,"With-store tick seconds":10,
                               "Paid movement model calls":0},
                },
            }
        if name == "restaurant":
            panels["persona"]["details"] += [
                f"ADK {variant} profile: "
                + (ROOT / f"config/agents/restaurant-adk/SOUL-{variant}.md")
                .read_text(encoding="utf-8")
                .strip()
                for variant in ("speed", "cost")
            ]
            panels["persona"]["sources"] += [
                f"config/agents/restaurant-adk/SOUL-{variant}.md" for variant in ("speed", "cost")
            ]
        for key, title, part, chapter in PARTS:
            panels[key].update(id=key, title=title, part=part, chapter=chapter)
        agents.append(
            dict(
                id=name,
                name=role.display_name,
                mission=role.mission,
                manifest=manifest,
                definition_hash=role.digest,
                accepts=list(accepted),
                emits=list(emitted),
                panels=list(panels.values()),
            )
        )
    edges = [
        dict(source=a["id"], target=b["id"], kind="event", topics=sorted(shared))
        for a in agents
        for b in agents
        if a != b and (shared := set(a["emits"]) & set(b["accepts"]))
    ]
    edges += [
        dict(source="scheduler", target=name, kind="a2a", topics=["JSON-RPC command"])
        for name in (*EVAL_ARMS, "inventory", "fulfillment")
    ]
    return dict(
        schema_version=1,
        input_fingerprint=input_fingerprint(),
        agents=agents,
        edges=edges,
        evidence=dict(
            release=release,
            verification=verified,
            chaos=chaos["chaos"]["metrics"],
            cost_per_delivery_eur=chaos["metrics"]["cost_per_delivery_eur"],
            cost_note="Historical seeded Chaos shift; synthetic operating cost, not model pricing.",
        ),
    )
