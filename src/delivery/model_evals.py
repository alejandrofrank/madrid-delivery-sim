"""Free, fresh-session model-arm experiments on the same native ADK evalsets."""

import json
import time
from pathlib import Path
from typing import Any

from google.adk.agents.run_config import RunConfig
from google.adk.evaluation.eval_set import EvalSet
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from delivery.adk_eval_agents import customer_agent, restaurant_agent
from delivery.customer_service import Advice
from delivery.eval_checks import code_checks
from delivery.golden_evals import evaluate_golden
from delivery.scenario_report import EvalAttempt, digest, summarize_arms
from delivery.trajectory_evals import score_trajectory

ROOT = Path(__file__).resolve().parents[2]


async def evaluate_model_arms(repeat: int = 1) -> dict[str, Any]:
    if not 1 <= repeat <= 100:
        raise ValueError("repeat must be between 1 and 100")
    rows = []
    fixture_hashes = {}
    for arm, filename, builder in (
        ("adk-offline-restaurant", "restaurant.evalset.json", restaurant_agent),
        ("adk-offline-customer", "customer_service.test.json", customer_agent),
    ):
        raw = json.loads((ROOT / "evals/adk" / filename).read_text(encoding="utf-8"))
        fixture_hashes[arm] = digest(raw)
        dataset = EvalSet.model_validate(raw)
        for case in dataset.eval_cases:
            assert case.conversation and case.session_input
            invocation = case.conversation[0]
            expected = invocation.intermediate_data
            reference = [dict(name=c.name, args=c.args) for c in expected.tool_uses]  # type: ignore[union-attr]
            for repetition in range(1, repeat + 1):
                agent = builder()
                service = InMemorySessionService()
                session = await service.create_session(
                    app_name=agent.name, user_id="eval", state=case.session_input.state.copy(),
                )
                runner = Runner(app_name=agent.name, agent=agent, session_service=service)
                started = time.perf_counter()
                calls, texts = [], []
                error = None
                try:
                    async for event in runner.run_async(
                        user_id="eval", session_id=session.id, new_message=invocation.user_content,
                        run_config=RunConfig(max_llm_calls=5),
                    ):
                        for part in (event.content.parts or []) if event.content else []:
                            if part.function_call:
                                calls.append({"name": part.function_call.name,
                                              "args": part.function_call.args or {},
                                              "allowed_tools": [getattr(t, "__name__", "")
                                                                for t in agent.tools]})
                            if part.text and not part.thought:
                                texts.append(part.text)
                except Exception as exc:
                    error = type(exc).__name__
                finally:
                    await runner.close()
                duration = (time.perf_counter() - started) * 1000
                text = texts[-1] if texts else ""
                failures = code_checks(calls=calls, response=text,
                                       response_schema=Advice if "customer" in arm else None)
                assert invocation.final_response
                expected_text = "".join(
                    p.text or "" for p in invocation.final_response.parts or []
                )
                score = score_trajectory({"calls": calls}, reference)
                categories = {
                    category: not any(f["category"] == category for f in failures)
                    for category in ("schema", "length", "invented_tool")
                }
                categories.update(task=error is None and text == expected_text,
                                  trajectory=score["ordered_match"] == 1)
                rows.append(EvalAttempt(
                    arm=arm, case_id=case.eval_id, repetition=repetition,
                    passed=all(categories.values()), categories=categories,
                    latency_ms=duration, cost_usd=0.0, reserved_usd=0.0, error=error,
                ))
    golden = evaluate_golden(ROOT / "data/evals/golden")
    return {
        "schema_version": 1, "kind": "model-evals", "mode": "scripted-offline",
        "fixture_hashes": fixture_hashes, "repeat": repeat,
        "rows": [r.model_dump() for r in rows], "arms": summarize_arms(rows), "golden": golden,
        "limitations": "Scripted contract evidence; not live-model reliability or latency. "
        "Bootstrap resamples distinct cases. Repeated fixed outputs do not add independent cases.",
    }
