"""Retain two small offline ADK runs for local UI inspection. No paid model calls."""

import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from delivery.adk_contracts import restaurant_template
from delivery.config import settings
from delivery.db import connect, migrate
from delivery.health_report import atomic_write_json, source_fingerprint
from delivery.supply import new_supply, replay_supply, run_supply
from delivery.supply_models import AgentDefinition, SupplyConfig, default_config


def configuration(profile: str) -> SupplyConfig:
    base = default_config()
    brain, soul = restaurant_template(profile)
    role = base.agents["restaurant"].model_dump()
    role.update(brain=brain, soul=soul, display_name="Elena" if profile == "speed" else "Mateo")
    role["limits"]["tool_calls_per_event"] = 16
    agent = AgentDefinition.model_validate(role)
    home = next(e for e in base.entities if e.kind == "household")
    restaurant = next(e for e in base.entities if e.id == "restaurant-pizza")
    markets = [e for e in base.entities if e.kind == "market"]
    entities = [
        home.model_copy(update={"node": 0, "recipe_ids": ("pizza",)}),
        restaurant.model_copy(update={"node": 1, "agent": agent}),
    ]
    entities += [
        market.model_copy(update={"node": node, "procurement_fee_cents": fee})
        for market, node, fee in zip(markets, [2, 8, 16], [300, 50, 100], strict=True)
    ]
    data = base.model_dump(mode="json")
    data.update(
        entities=[e.model_dump(mode="json") for e in entities],
        start_hour=12,
        duration_minutes=15,
        playback_seconds=0,
        calls_per_household=1,
        restaurant_stock_servings=0,
        market_stock_servings=3,
    )
    return SupplyConfig.model_validate(data)


def main() -> None:
    database = urlsplit(settings().database_url)
    if database.hostname not in {
        "postgres",
        "localhost",
        "127.0.0.1",
        "::1",
    } or database.path not in {
        "/delivery",
        "/delivery_test",
    }:
        raise ValueError("The ADK demo requires this project's local database")
    migrate()
    results = []
    for profile, expected in (("speed", "market-a"), ("cost", "market-b")):
        run = new_supply(configuration(profile))
        state = run_supply(run)
        replay = replay_supply(run)
        with connect() as conn:
            decision = conn.execute(
                "SELECT result FROM restaurant_turns WHERE run_id=%s ORDER BY event_id LIMIT 1",
                (run,),
            ).fetchone()["result"]
        if (
            decision["supplier"] != expected
            or state["metrics"]["delivered"] != 1
            or not replay["matches"]
        ):
            raise RuntimeError("Offline ADK comparison did not meet its declared criteria")
        results.append(
            {
                "profile": profile,
                "run": run,
                "url": f"http://localhost:8010/restaurant-lab?run={run}",
                "supplier": decision["supplier"],
                "metrics": state["metrics"],
                "invariants": state["invariants"],
                "replay_matches": replay["matches"],
            }
        )
    root = Path(__file__).resolve().parents[1]
    receipt = {
        "created_at": datetime.now(UTC).isoformat(),
        "engine": "google_adk",
        "adk_version": version("google-adk"),
        "model": "scripted offline fixture",
        "paid_calls": 0,
        "source_fingerprint": source_fingerprint(root),
        "profiles": results,
    }
    atomic_write_json(root / "artifacts/adk-restaurants-demo.json", receipt)
    print(json.dumps(receipt, indent=2, default=str))


if __name__ == "__main__":
    main()
