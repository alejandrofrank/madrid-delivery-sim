"""Read-only deployed smoke check; probes rejected writes with an empty body."""

import argparse
import json
import urllib.error
import urllib.request


def verify(origin: str) -> None:
    if not origin.startswith(("https://", "http://127.0.0.1:")):
        raise ValueError("Expected HTTPS or a loopback preview")

    def get(path: str) -> dict:
        with urllib.request.urlopen(origin.rstrip("/") + path, timeout=45) as response:
            return json.load(response)

    assert get("/api/runtime")["mode"] == "replay"
    first = get("/api/state?t=0")
    last = get("/api/state?t=60")
    assert first["run"]["sim_time"] == 0
    assert last["run"]["status"] == "complete"
    assert last["replay"]["paid_calls"] == 0
    assert first == get("/api/state?t=0"), "Playback must be independent of other clients"
    for path in ["/api/runs", "/api/chaos", "/a2a/dispatcher/", "/mcp/"]:
        try:
            urllib.request.urlopen(urllib.request.Request(
                origin.rstrip("/") + path, data=b"{}",
                headers={"Content-Type": "application/json"}, method="POST",
            ), timeout=30)
        except urllib.error.HTTPError as error:
            assert error.code == 405, (path, error.code)
        else:
            raise AssertionError(f"Public write unexpectedly succeeded: {path}")
    print("Replay verified: deterministic playback, completed shift, no models, writes denied.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    verify(parser.parse_args().url)
