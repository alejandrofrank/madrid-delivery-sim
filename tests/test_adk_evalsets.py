"""Both public Google eval entrypoints, with hard network denial."""

import asyncio
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.evaluation.eval_set import EvalSet

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("agent,file", [
    ("restaurant", "restaurant.evalset.json"),
    ("customer_service", "customer_service.test.json"),
    ("customer_service", "customer_policy.evalset.json"),
    ("chaos_dispatcher", "chaos_dispatcher.evalset.json"),
    ("chaos_restaurant", "chaos_restaurant.evalset.json"),
    ("chaos_customer", "chaos_customer.evalset.json"),
])
def test_agent_evaluator_offline(agent, file, monkeypatch, tmp_path):
    import httpx
    import requests
    from google import genai

    def forbidden(*args, **kwargs):
        pytest.fail("Offline evaluation attempted network/provider initialization")

    monkeypatch.setattr(genai, "Client", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.syspath_prepend(str(ROOT))
    output = tmp_path / "results.csv"
    asyncio.run(AgentEvaluator.evaluate(
        agent_module=f"evals.adk.{agent}",
        eval_dataset_file_path_or_dir=str(ROOT / "evals/adk" / file),
        num_runs=1, output_file=str(output),
    ))
    assert list(csv.DictReader(output.open()))


@pytest.mark.parametrize("agent,file", [
    ("restaurant", "restaurant.evalset.json"),
    ("customer_service", "customer_service.test.json"),
    ("customer_service", "customer_policy.evalset.json"),
    ("chaos_dispatcher", "chaos_dispatcher.evalset.json"),
    ("chaos_restaurant", "chaos_restaurant.evalset.json"),
    ("chaos_customer", "chaos_customer.evalset.json"),
])
def test_adk_eval_cli_offline(agent, file, tmp_path):
    # ADK persists .adk below its application directory. Image sources are owned
    # by root, while CI runs as an unprivileged user; never write into the repo.
    applications = tmp_path / "applications"
    shutil.copytree(ROOT / "evals/adk", applications, ignore=shutil.ignore_patterns(".adk"))
    # Deny sockets in the child too; SDK package installation happens before this test.
    (tmp_path / "sitecustomize.py").write_text(
        "import socket\n"
        "def deny(*a, **kw): raise RuntimeError('Network forbidden in offline ADK eval')\n"
        "socket.create_connection = deny\n"
        "socket.socket.connect = deny\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), str(ROOT),
                                                      str(ROOT / "src")]),
           "GOOGLE_API_KEY": "", "GEMINI_API_KEY": "", "LLM_PROVIDER": "disabled"}
    result = subprocess.run(
        [str(Path(sys.executable).with_name("adk")), "eval", str(applications / agent),
         str(applications / file), "--config_file_path",
         str(applications / "test_config.json")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    count = len(EvalSet.model_validate_json((applications / file).read_text()).eval_cases)
    assert f"Tests passed: {count}" in result.stdout, result.stdout


def test_evalset_schema_and_personas_are_separate():
    import json

    from google.adk.evaluation.conversation_scenarios import ConversationScenario

    for name in ("restaurant.evalset.json", "customer_service.test.json"):
        value = EvalSet.model_validate_json((ROOT / "evals/adk" / name).read_text())
        assert len(value.eval_cases) == 10
        assert all(c.conversation and not c.conversation_scenario for c in value.eval_cases)
    personas = json.loads((ROOT / "evals/adk/personas/customer_service.scenarios.json").read_text())
    for scenario in personas["scenarios"]:
        ConversationScenario.model_validate(scenario)
