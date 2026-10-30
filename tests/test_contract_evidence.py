"""The operator can inspect fixed retained receipts without starting providers or a DB."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from delivery.api import local_mutations
from delivery.supply_api import router


def test_contract_receipts_are_fixed_read_only_local_operator_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.middleware("http")(local_mutations)
    app.include_router(router)
    client = TestClient(app)
    path = "/api/supply/contract-verification"
    assert client.get(path).status_code == 404
    directory = tmp_path / "artifacts"
    directory.mkdir()
    for name in ("verification", "followup", "final"):
        (directory / f"adk-contract-{name}.json").write_text(json.dumps({"case": name}))
        response = client.get(path + "?file=../../private.json")
        assert response.status_code == 200
        assert response.json() == {"case": name}
    assert client.post(path).status_code == 405
    assert client.get(path, headers={"Host": "remote.example"}).status_code == 403
