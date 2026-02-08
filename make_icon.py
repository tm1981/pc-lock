"""
Convert pclock_icon.png to pclock.ico with multiple sizes.
"""
from PIL import Image
from pathlib import Path

# Paths
SRC = Path(__file__).with_name('assets') / 'pclock_icon.png'
OUT = Path(__file__).with_name('assets') / 'pclock.ico'
OUT.parent.mkdir(parents=True, exist_ok=True)

# Standard ICO sizes
sizes = [16, 24, 32, 48, 64, 128, 256]

# Load source image
source = Image.open(SRC)
if source.mode != 'RGBA':
    source = source.convert('RGBA')

# Create resized versions for ICO - Pillow wants [(size, size)] tuples in save
resized_images = []
for s in sizes:
    resized = source.resize((s, s), Image.Resampling.LANCZOS)
    resized_images.append(resized)

# Save ICO - Pillow handles multi-size ICO when we pass the sizes directly
source.save(OUT, format='ICO', sizes=[(s, s) for s in sizes])
print(f"Converted {SRC} -> {OUT}")
print(f"Sizes: {sizes}")
