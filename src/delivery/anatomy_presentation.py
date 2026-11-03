"""Plain-language presentation derived from the public anatomy contracts."""

from typing import Any

from delivery.agent_specs import RoleSpec

LABELS = {
    "mission": ("What it does", "Role and mission"),
    "persona": ("Personality and rules", "Persona \u00b7 SOUL"),
    "tools": ("Actions it can take", "Tools"),
    "memory": ("What it remembers", "Memory and scope"),
    "policy": ("Rules it cannot break", "Guardrails"),
    "limits": ("Spending limits", "Budget"),
    "model": ("How it decides", "Model and routing"),
    "protocols": ("Talks to other agents", "A2A \u00b7 MCP"),
    "events": ("Reacts to events", "Events"),
    "evals": ("Tested on unseen cases", "Evals"),
    "environment": ("Where it works", "Environment"),
}
LIMIT_LABELS = {
    "events_per_run": "Events allowed per run",
    "tool_calls_per_event": "Tool calls allowed per event",
    "tool_calls_per_run": "Tool calls allowed per run",
    "memory_entries": "Stored observations allowed",
    "memory_bytes": "Memory storage limit (bytes)",
    "model_calls": "Model calls allowed per run",
    "model_tokens": "Model tokens allowed per run",
    "model_usd": "Model spending limit per run (USD)",
}
MEMORY_LABELS = {
    "mode": "Recall format",
    "max_facts": "Facts recalled at once",
    "max_bytes": "Recall limit (bytes)",
    "ttl_seconds": "Default expiry (simulation seconds)",
}
INTRODUCTIONS = {
    "household": "It places meal orders and approves ingredient substitutions.",
    "restaurant": "It decides which orders a kitchen can accept and when.",
    "market": "It finds a supplier when a kitchen needs ingredients.",
    "inventory": "It checks stock and sets aside the items an order needs.",
    "fulfillment": "It picks items from shelves, packs the bag and takes it to the dock.",
    "dispatcher": "It chooses a courier and changes the delivery plan when needed.",
    "courier": "It collects the order and follows its route to the customer.",
    "customer_service": "It explains delivery problems and applies refund or escalation rules.",
    "judge": "It checks recovery decisions and records whether they followed the rules.",
}
ROLE_VISUALS = {
    "inventory": ("#75d2a8", "stock", "Stock"),
    "fulfillment": ("#e9bc71", "pick", "Pick"),
    "dispatcher": ("#8db9e3", "dispatch", "Route"),
    "courier": ("#23d8ce", "deliver", "Deliver"),
    "judge": ("#e5eef5", "review", "Review"),
    "household": ("#f28e8e", "home", "Customer"),
    "restaurant": ("#db9669", "kitchen", "Kitchen"),
    "market": ("#bdcf7c", "supply", "Supply"),
    "customer_service": ("#b9a5dd", "support", "Support"),
}

ARM_LABELS = {
    "adk-offline-restaurant": "Kitchen decisions",
    "adk-chaos-restaurant": "Kitchen disruption recovery",
    "adk-offline-customer": "Complaint classification",
    "adk-customer-policy": "Refund and escalation policy",
    "adk-chaos-customer": "Customer disruption recovery",
    "adk-chaos-dispatcher": "Courier reassignment",
}


def tool_icon(name: str) -> str:
    if "memory" in name:
        return "memory"
    if any(word in name for word in ("read", "search", "pantry", "stock", "recipe")):
        return "search"
    if any(word in name for word in ("refund", "approve", "judge", "escalate")):
        return "shield"
    if any(word in name for word in ("contact", "offer", "message")):
        return "message"
    if any(word in name for word in ("route", "dispatch", "assign", "deliver")):
        return "route"
    if any(word in name for word in ("prep", "cook", "wait", "time")):
        return "clock"
    return "box"


def enrich_agent(agent: dict[str, Any], role: RoleSpec, release: dict[str, Any]) -> None:
    name = role.role
    panels = {p["id"]: p for p in agent["panels"]}
    agent["introduction"] = f"This is the {agent['name']} agent. {INTRODUCTIONS[name]}"
    tools = [
        {
            "id": t,
            "description": role.tool_descriptions[t],
            "context": "Role tool",
            "icon": tool_icon(t),
        }
        for t in role.tools
    ]
    tools += [
        {
            "id": t,
            "description": t.replace("_", " ").capitalize(),
            "context": "Disruption recovery only",
            "icon": tool_icon(t),
        }
        for t in role.recovery_tools
    ]
    agent["tools"] = tools
    preferred = [t for t in tools if not t["id"].startswith("memory.")]
    agent["tool_badges"] = (preferred or tools)[:4]
    agent["badge"] = agent["name"]
    color, symbol, short_label = ROLE_VISUALS[name]
    agent["visual"] = {"color": color, "symbol": symbol, "label": short_label}
    # Same USD unit for every role. This is a ceiling, never a remaining balance.
    budget = float(
        panels["limits"]["numbers"].get("Default run budget (USD)", role.limits.model_usd)
    )
    agent["budget"] = {
        "value": budget,
        "unit": "USD / run",
        "label": "Default model spending cap",
        "note": "Configured limit, not money spent. Optional profiles have separate limits.",
    }
    results = panels["evals"]["results"]
    heads: dict[str, tuple[str, Any, str, list[str]]] = {
        "mission": (
            "One role, one responsibility",
            1,
            "agent role",
            [role.mission, role.why_it_exists],
        ),
        "persona": (
            "Personality never adds permissions",
            0,
            "extra permissions",
            [
                "The SOUL file describes how this agent should behave.",
                "Its tools and limits still come from the role configuration.",
            ],
        ),
        "tools": (
            "Only approved actions are available",
            len(tools),
            "approved tools",
            [
                f"{len(role.tools)} role tools; "
                f"{len(role.recovery_tools)} separate recovery tools.",
                "Each tool checks its inputs and the order it may affect.",
            ],
        ),
        "memory": (
            "Remembers only within its assigned scope",
            8,
            "facts recalled at once",
            [
                "Records stay tied to a run, role and order.",
                "Explore the actual record and the agent's input below.",
            ],
        ),
        "policy": (
            "No unrestricted access to the system",
            0,
            "unrestricted SQL or shell tools",
            [
                "Messages and memories cannot grant new permissions.",
                "Fixed code checks actions before they change the simulation.",
            ],
        ),
        "limits": (
            "Model spending has a configured ceiling",
            "$" + format(budget, ".2f"),
            "USD per run",
            [
                "This is the checked-in default, not a live balance.",
                f"At most {role.limits.tool_calls_per_event} role-tool calls per event.",
                "Optional ADK and cloud profiles keep separate limits.",
            ],
        ),
        "model": (
            "Routine work needs no model",
            0,
            "routine model calls",
            [
                "Fixed code handles ordinary simulation decisions.",
                "The selected profile determines whether a model can be used.",
            ],
        ),
        "protocols": (
            "Uses a published agent interface"
            if panels["protocols"]["card"]
            else "Hands work over through queued events",
            int(panels["protocols"]["card"] is not None),
            "A2A server cards",
            [
                "A2A carries structured requests between supported agents.",
                "MCP lets external agents read simulation facts; it grants no write access.",
            ],
        ),
        "events": (
            "Responds when relevant work arrives",
            len(agent["accepts"]),
            "incoming event types",
            [
                f"Can publish {len(agent['emits'])} types of result.",
                "Durable handoffs let interrupted work be retried safely.",
            ],
        ),
        "environment": (
            "Runs without paid model calls by default",
            0,
            "paid calls from this page",
            [
                "Local services keep the simulation and its records together.",
                "The public cloud replay shows recordings, not live agents.",
            ],
        ),
    }
    if name == "customer_service":
        heads["memory"] = (
            "Starts fresh for each complaint",
            0,
            "persistent recall tools",
            [
                "The classifier receives only the current complaint.",
                "Receipts prevent duplicate billing; they are not recalled memory.",
            ],
        )
        cap = panels["policy"]["numbers"]["Automatic overdue refund maximum (EUR)"]
        heads["policy"] = (
            "Automatic overdue refunds are capped",
            f"\u20ac{cap:g}",
            "maximum automatic refund",
            ["Requests above \u20ac100 need approval.", "A model cannot change the refund policy."],
        )
        heads["model"] = (
            "One bounded classification call",
            1,
            "call per complaint",
            [
                "ADK classifies the complaint; fixed policy decides money.",
                "Disabled providers send unresolved requests to operator review.",
            ],
        )
    if name == "restaurant":
        heads["model"] = (
            "Choose fixed rules or an ADK agent",
            panels["model"]["numbers"]["ADK calls / event"],
            "maximum ADK calls per event",
            [
                "Fixed rules are the default; offline ADK uses scripted decisions.",
                "An enabled model is optional and stays inside its tool limits.",
            ],
        )
    if name != "customer_service":
        defaults = panels["memory"]["reference"]["profile_defaults"]
        heads["memory"] = (
            "Remembers only within its assigned scope",
            defaults["max_facts"],
            "facts recalled at once",
            [
                f"Up to {defaults['max_bytes']:,} bytes in a recall.",
                f"Default expiry: {defaults['ttl_seconds'] // 60} simulated minutes.",
                "Records stay tied to a run, role and order.",
            ],
        )
    if results:
        cases = sum(row["cases"] for row in results)
        score = sum(row["cases"] * row["pass_power_k"] for row in results) / cases
        heads["evals"] = (
            "Success on recorded unseen cases",
            f"{score:.0%}",
            "cases passing all attempts",
            [
                f"{cases} held-out cases across {len(results)} test groups.",
                f"{release['repeat']} attempts per case; recorded {release['created_at'][:10]}.",
                "Scripted offline tests, not a live-model reliability claim.",
            ],
        )
    else:
        heads["evals"] = (
            "No separate held-out score is published",
            0,
            "published held-out test groups",
            [
                "This role is checked in deterministic workflow tests.",
                "A whole-project test count is not a per-agent pass rate.",
            ],
        )
    for key, panel in panels.items():
        panel["label"], panel["technical_label"] = LABELS[key]
        if key == "evals" and not results:
            panel["label"] = "How it is tested"
        panel["number_rows"] = [
            {"label": MEMORY_LABELS.get(label, label), "value": value}
            for label, value in panel["numbers"].items()
        ]
        title, value, unit, bullets = heads[key]
        panel["headline"] = {"text": title, "value": value, "unit": unit, "bullets": bullets}
    panels["evals"]["result_labels"] = ARM_LABELS
    card = panels["protocols"]["card"]
    fields = []
    if card:
        for key, label in (
            ("name", "Agent name"),
            ("description", "Purpose"),
            ("version", "Agent version"),
            ("protocolVersion", "A2A version"),
        ):
            if key in card:
                fields.append({"label": label, "value": str(card[key])})
        for interface in card.get("supportedInterfaces", []):
            fields.append(
                {
                    "label": "Connection",
                    "value": " / ".join(
                        str(interface[k])
                        for k in ("protocolBinding", "protocolVersion", "url")
                        if k in interface
                    ),
                }
            )
        for skill in card.get("skills", []):
            fields.append(
                {
                    "label": skill.get("name", skill.get("id", "Skill")),
                    "value": skill.get("description", ""),
                }
            )
        for key, label in (
            ("defaultInputModes", "Accepted input"),
            ("defaultOutputModes", "Returned output"),
        ):
            fields.append({"label": label, "value": ", ".join(card.get(key, []))})
        for key, value in card.get("capabilities", {}).items():
            label = {
                "streaming": "Streaming",
                "pushNotifications": "Push notifications",
                "stateTransitionHistory": "State history",
            }.get(key, key)
            fields.append({"label": label, "value": "Supported" if value else "Not supported"})
    panels["protocols"]["card_fields"] = fields


def order_story(agents: list[dict[str, Any]]) -> dict[str, Any]:
    available = {agent["id"] for agent in agents}
    steps = [
        (
            None,
            "Customer order",
            "The demo submits a store order",
            "asks if items are in stock",
            "event",
        ),
        (
            "inventory",
            "Stock check",
            "Reserves the available items",
            "sends the reserved pick list to",
            "a2a",
        ),
        (
            "fulfillment",
            "Pick and pack",
            "Moves the bag from shelf to dock",
            "hands the packed bag to",
            "event",
        ),
        (
            "dispatcher",
            "Courier dispatch",
            "Finds a courier for the packed order",
            "assigns a delivery route to",
            "event",
        ),
        (
            "courier",
            "Delivery",
            "Takes the order to the doorstep",
            "leaves its decisions for",
            "review",
        ),
        ("judge", "Judge review", "Checks recovery policy and outcomes", "", "review"),
    ]
    return {
        "title": "One order, a team of agents",
        "summary": "Follow an order from the stock check to the doorstep, then inspect any agent.",
        "note": (
            "Illustrated dark-store journey, not live activity. The demo creates the order; "
            "the controller routes agent requests. The judge reviews recovery evidence."
        ),
        "steps": [
            {"agent": role, "label": label, "summary": summary, "handoff": handoff, "kind": kind}
            for role, label, summary, handoff, kind in steps
            if role is None or role in available
        ],
        "support": [
            {
                "agent": "household",
                "summary": "For meals, represents the customer and approves substitutions.",
            },
            {
                "agent": "restaurant",
                "summary": "For meals, the kitchen checks recipes, ingredients and consent.",
            },
            {"agent": "market", "summary": "Finds ingredient suppliers when the kitchen is short."},
            {
                "agent": "customer_service",
                "summary": "Explains delays and applies refund or escalation policy.",
            },
        ],
        "legend": [
            {
                "kind": "event",
                "label": "Parcel route",
                "detail": "The bag moves from stock to packing, then to the doorstep.",
            },
            {
                "kind": "a2a",
                "label": "Agent request (A2A)",
                "detail": "A typed request routed by the controller.",
            },
            {
                "kind": "review",
                "label": "Review evidence",
                "detail": "The judge reads decisions; it does not deliver orders.",
            },
        ],
    }
