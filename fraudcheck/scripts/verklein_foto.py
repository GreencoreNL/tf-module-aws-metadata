"""Maakt een verkleinde kopie van een foto die te groot is om te uploaden (grens ongeveer 3 MB).

  python scripts/verklein_foto.py <foto> <uitvoer.jpg> [max_mb]

Behoudt de EXIF opnamedatum. Verkleint stap voor stap tot het bestand onder max_mb (standaard 2,5) zit.
"""
import io
import sys

from PIL import Image, ImageOps

src, dst = sys.argv[1], sys.argv[2]
max_bytes = float(sys.argv[3] if len(sys.argv) > 3 else 2.5) * 1024 * 1024
im = Image.open(src)
exif = im.info.get("exif", b"")
im = ImageOps.exif_transpose(im).convert("RGB")
for side in (3000, 2400, 2000, 1600, 1280):
    tmp = im.copy()
    tmp.thumbnail((side, side))
    for q in (88, 80, 72):
        buf = io.BytesIO()
        tmp.save(buf, "JPEG", quality=q, optimize=True, exif=exif)
        if buf.tell() <= max_bytes:
            open(dst, "wb").write(buf.getvalue())
            print(f"{dst} {buf.tell() / 1024 / 1024:.1f} MB ({tmp.size[0]}x{tmp.size[1]}, kwaliteit {q})")
            sys.exit(0)
sys.exit("Kon de foto niet klein genoeg maken")
