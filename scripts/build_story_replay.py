"""Export or verify the static story recording without starting any services."""

import argparse
from pathlib import Path

from delivery.story_replay import build_story_replay, encode_story_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/replays"))
    parser.add_argument("--output", type=Path, default=Path("web/data/story-replay.json"))
    parser.add_argument("--run", help="Recorded run ID; defaults to the first reviewed recording")
    parser.add_argument("--check", action="store_true",
                        help="Fail if the committed export has drifted")
    args = parser.parse_args()
    raw = encode_story_replay(build_story_replay(args.source, args.run))
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != raw:
            raise SystemExit("Story recording has drifted; run scripts/build_story_replay.py")
        print(f"Story recording verified ({len(raw):,} bytes).")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
        print(f"Wrote {args.output} ({len(raw):,} bytes).")


if __name__ == "__main__":
    main()
