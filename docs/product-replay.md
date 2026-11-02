# Recorded product examples

The story landing uses a committed static projection of a reviewed offline
recording. Downloading this file does not start a simulation, connect to a
database, call a model, or require a running application backend.

## City recording

- Input: the first recording in `data/replays/manifest.json`, currently seed 42.
  The existing replay loader verifies its SHA-256 hash and rejects paid calls,
  unfinished runs and invalid frame sequences.
- Output: `web/data/story-replay.json`. Its source block records the original
  filename, hash, run ID, creation time and offline provider.
- Clock: two simulated hours, presented in 60 seconds. The recording has 121
  snapshots and 42 couriers. Playback must interpolate the active recorded route
  between snapshots; stationary or offline couriers stay at their snapshot
  position. Route waiting points and millisecond timing are preserved.
- Map: the recording's actual OpenStreetMap streets and site locations.
  Coordinates are quantized to an 8192-unit rectangle. `map.bounds` allows
  conversion back to longitude and latitude; `map.aspect_ratio` prevents the map
  from being stretched. Duplicate reverse streets are removed, and road-only
  bends are simplified within three map units (under four metres in this
  recording). Courier paths are not simplified. Keep the OpenStreetMap credit.
- Store activity: order creation times come from the recording. Each store is
  identified by the `picked_up` decision's store ID, because names such as
  Mercadona are shared by several branches. Missing evidence produces a null
  site; the renderer must not guess where to pulse.
- Outcomes: 71 of 71 orders on time, five of five disruptions resolved, and
  €1.4903 estimated fleet operating cost per delivery. These are **offline
  simulation results**, not measurements of live model quality or commercial
  delivery costs. Recovery requires an ended event, a measured recovery time,
  no unresolved orders and no lost orders. Disruption cohorts overlap and must
  not be summed.

The city recording contains no in-store inventory or picking snapshots. Do not
present an illustrated shelf-to-doorstep explanation as measured store activity
from this file. Store examples need their own recorded evidence.

## Regeneration and checks

From an environment with the project installed:

```bash
python3 scripts/build_story_replay.py
python3 scripts/build_story_replay.py --check
python3 -m pytest -q tests/test_story_replay.py tests/test_replay.py
```

The builder is deterministic and makes no network requests. The committed export
must match regeneration byte for byte. Tests also verify recorded outcome
provenance, waiting periods, offline states, exact store selection, missing
evidence, rejected tampering and invalid route times.

The download budget is 900,000 uncompressed bytes and 220,000 gzip-compressed
bytes. The current file is about 712 KB before compression. This is a static data
asset; the actual compression sent over HTTP depends on the deployment. Robots,
fonts and other presentation assets have separate budgets.

## Consumer contract

`frames[].couriers` follows the order of the top-level `couriers` roster. Each
entry is `[x, y, statusIndex, routeIndex]`; `-1` means there is no moving route.
`statuses` names the indexes. Route points are `[x, y, simulatedSeconds]`.
Choose the latest frame at or before the playback time and interpolate only its
referenced route. Equal-position points with different times represent waiting.

`orders[].site` indexes `map.sites`, and `orders[].courier` indexes `couriers`.
Null references are intentional. Raw IDs belong in source details, not the
visitor-facing explanation. Labels must distinguish recorded examples from a
new run, and visible motion must pause off-screen and respect reduced motion.
