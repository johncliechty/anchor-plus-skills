"""Downsample the three house-reference skill icons to 24px for the named defeater."""
from pathlib import Path
from PIL import Image

src_dir = Path(r"<path>")
out_dir = Path(r"<path> Foundry\skills\jumper\_refuter-24px")
out_dir.mkdir(exist_ok=True)

jobs = [
    ("jumper", src_dir / "ref-jumper.jpg"),
    ("researchprime", src_dir / "ref-researchprime.jpg"),
    ("steward", src_dir / "icon.jpg"),
]

for name, src in jobs:
    img = Image.open(src).convert("RGB")
    print(f"{name} native={img.size} mode={img.mode}")
    small = img.resize((24, 24), Image.Resampling.LANCZOS)
    small.save(out_dir / f"{name}-24.png")
    # nearest-neighbor 8x so 24px pixels are inspectable without interpolation
    small.resize((192, 192), Image.Resampling.NEAREST).save(out_dir / f"{name}-24-x8.png")
    print(f"wrote {name}-24.png and {name}-24-x8.png")

print("done")
