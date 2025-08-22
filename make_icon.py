from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

OUT = Path(__file__).with_name('assets') / 'pclock.ico'
OUT.parent.mkdir(parents=True, exist_ok=True)

sizes = [16, 24, 32, 48, 64, 128, 256]
images = []

for s in sizes:
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # background rounded square with gradient
    # simple two-tone gradient
    for y in range(s):
        t = y / max(1, s - 1)
        r = int(56 + (246 - 56) * t)   # 0x38 -> 0xF6
        g = int(34 + (173 - 34) * t)   # 0x22 -> 0xAD
        b = int(131 + (31 - 131) * t)  # 0x83 -> 0x1F
        d.line([(0, y), (s, y)], fill=(r, g, b, 255))
    # rounded mask
    mask = Image.new('L', (s, s), 0)
    m = ImageDraw.Draw(mask)
    radius = max(3, s // 6)
    m.rounded_rectangle([1, 1, s - 2, s - 2], radius=radius, fill=255)
    img = Image.composite(img, Image.new('RGBA', (s, s), (0, 0, 0, 0)), mask)

    d = ImageDraw.Draw(img)
    # lock body
    pad = max(2, s // 8)
    body_top = int(s * 0.5)
    d.rounded_rectangle([pad, body_top, s - pad, s - pad], radius=max(2, s // 10), fill=(20, 20, 20, 230))
    # shackle
    sw = max(2, s // 10)
    arc_box = [pad + sw, pad, s - pad - sw, body_top + sw * 2]
    d.arc(arc_box, start=210, end=-30, fill=(20, 20, 20, 230), width=sw)
    images.append(img)

# Save ICO
images[0].save(OUT, sizes=[(s, s) for s in sizes])
print(f"Wrote icon to {OUT}")
