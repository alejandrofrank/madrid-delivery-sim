"""Fail CI if a completed run loses work or violates assignment/refund invariants."""

import json
from pathlib import Path

paths = sorted(Path("artifacts").glob("run-*.json"), key=lambda p: p.stat().st_mtime)
assert paths, "No exported run"
state = json.loads(paths[-1].read_text())
assert state["run"]["status"] == "complete"
assert state["run"]["sim_time"] == 43200
assert state["metrics"]["orders"] == 247  # pinned graph + seed 42 regression baseline
assert state["metrics"]["delivered"] == 247
assert state["metrics"]["active"] == 0
assert state["queue"].get("dead", 0) == 0
assert state["queue"].get("ready", 0) == 0
assert state["queue"].get("leased", 0) == 0
assert state["queue"]["done"] == 996
assert len(state["complaints"]) == 4
assert all(c["approved_refund_eur"] <= 5 for c in state["complaints"])
print("Full-day invariants passed: 247 deliveries, 996 ACKs, no stranded work.")
