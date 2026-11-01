"""Contract and equivalence checks for the physical environment boundary."""

from unittest.mock import MagicMock

import pytest

from delivery.environment import Environment
from delivery.madrid_city import MadridCity


def test_madrid_implements_environment() -> None:
    assert isinstance(MadridCity(MagicMock()), Environment)


def test_city_tick_preserves_existing_effect_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    conn, courier = MagicMock(), MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "seed": 42, "duration": 3600, "sim_time": 0, "chaos_config": {}
    }
    courier.advance.side_effect = lambda *args: calls.append("courier")
    monkeypatch.setattr("delivery.madrid_city.physical_tick", lambda *a: calls.append("chaos"))
    monkeypatch.setattr("delivery.madrid_city.observe", lambda *a: calls.append("observe"))
    monkeypatch.setattr("delivery.simulation.generate", lambda *a: calls.append(a[2:]))
    city = MadridCity(MagicMock(), courier)
    assert city.advance(conn, "run", 60)["chaos"] is True
    assert calls == ["courier", "chaos", (60, 42, 3600), "observe"]


def test_environment_reads_are_scoped_and_cursor_bounded() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"sim_time": 42}
    conn.execute.return_value.fetchall.return_value = []
    city = MadridCity(MagicMock())
    assert city.clock(conn, "chosen-run") == 42
    assert city.read(conn, "chosen-run")["sim_time"] == 42
    assert city.events(conn, "chosen-run", 15) == []
    assert conn.execute.call_args.args[1] == ("chosen-run", 15)
    assert "LIMIT 500" in conn.execute.call_args.args[0]
    with pytest.raises(ValueError, match="cursor"):
        city.events(conn, "chosen-run", -1)


def test_environment_rejects_unknown_run_and_backwards_time() -> None:
    conn = MagicMock()
    city = MadridCity(MagicMock())
    conn.execute.return_value.fetchone.return_value = None
    with pytest.raises(ValueError, match="Unknown run"):
        city.clock(conn, "missing")
    with pytest.raises(ValueError, match="Unknown run"):
        city.advance(conn, "missing", 0)
    conn.execute.return_value.fetchone.return_value = {"sim_time": 90}
    with pytest.raises(ValueError, match="backwards"):
        city.advance(conn, "run", 60)
