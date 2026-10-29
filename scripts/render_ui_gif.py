"""Encode the actual browser capture as a short README GIF. Requires Pillow (dev only)."""
from pathlib import Path
import argparse
import json
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--frames", default="artifacts/ui-demo-frames")
parser.add_argument("--out", default="docs/media/ui-demo.gif")
args = parser.parse_args()
source = Path(args.frames)
metadata = json.loads((source / "metadata.json").read_text())
frames = []
for path in sorted(source.glob("frame-*.png")):
    with Image.open(path) as image:
        frames.append(image.convert("RGB").resize((1080, 720), Image.Resampling.LANCZOS))
palette = frames[len(frames) // 2].quantize(colors=128)
frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
output = Path(args.out)
output.parent.mkdir(parents=True, exist_ok=True)
duration = max(50, round(metadata["durationMs"] / len(frames) / 10) * 10)
frames[0].save(output, save_all=True, append_images=frames[1:], duration=duration, loop=1, optimize=True, disposal=1)
output.with_suffix(".json").write_text(json.dumps({**metadata, "encodedFrameMs": duration, "width":1080, "height":720, "loops":2}, indent=2)+"\n")
print(f"Saved {output}: {output.stat().st_size:,} bytes")
