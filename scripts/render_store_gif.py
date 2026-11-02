"""Encode the actual store browser recording. Requires Pillow (development only)."""
import json
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
recording = json.loads((root / "artifacts/dark-store/recording.json").read_text())
paths = [root / "artifacts/dark-store/frames/000.png"]
paths.extend(root / row["file"] for row in recording["frames"])
frames = []
for path in paths:
    with Image.open(path) as image:
        frames.append(image.convert("RGB").resize((1080, 760), Image.Resampling.LANCZOS))
palette = frames[len(frames) // 2].quantize(colors=128)
frames = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in frames]
target = root / "docs/media/store-journey.gif"
target.parent.mkdir(parents=True, exist_ok=True)
frames[0].save(
    target,
    save_all=True,
    append_images=frames[1:],
    duration=[1500] + [1000] * (len(frames) - 2) + [2500],
    loop=0,
    optimize=True,
    disposal=1,
    comment=b"Actual madrid-delivery-sim browser session; seed 42; NVIDIA SimReady / codepawl models CC BY 4.0. See docs/DARK-STORE.md.",
)
target.with_suffix(".json").write_text(
    json.dumps(
        dict(
            source="Actual local browser recording; scripts/record_store_demo.cjs",
            run=recording["run"],
            seed=42,
            chaos="robot_breakdown",
            delivered=recording["delivered"],
            frame_count=len(frames),
            frame_interval_ms=1000,
            endpoint_holds_ms=[1500, 2500],
            size=[1080, 760],
            render=recording["stats"],
            asset_credit="NVIDIA SimReady, converted by codepawl, CC BY 4.0",
            asset_manifest="web/vendor/simready/manifest.json",
        ),
        indent=2,
    ) + "\n"
)
print(f"Saved {target.name}: {target.stat().st_size:,} bytes")
