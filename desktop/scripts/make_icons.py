# /// script
# requires-python = ">=3.11"
# ///
"""Generate the minimal PNG icon set Tauri needs for `tauri dev`, with no image deps.

Draws a flat rounded-square glyph (a 3x3 "fleet" dot grid) at each required size using only the
stdlib (struct + zlib). For full bundling (.icns/.ico) run `pnpm tauri icon dist-icon.png`
afterwards; this script alone is enough to launch `tauri dev`.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src-tauri" / "icons"
BG = (37, 35, 64)  # #252340
FG = (124, 196, 255)  # #7cc4ff


def png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter: none
        raw.extend(pixels[y * stride : (y + 1) * stride])
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def render(size: int) -> bytes:
    buf = bytearray(size * size * 4)
    r = size // 8
    cells = 3
    margin = size // 5
    span = size - 2 * margin
    step = span / (cells - 1) if cells > 1 else 0
    dot = max(1, size // 16)
    centers = [
        (int(margin + i * step), int(margin + j * step))
        for i in range(cells)
        for j in range(cells)
    ]

    def in_rounded(x: int, y: int) -> bool:
        if r <= 0:
            return True
        for cx, cy in ((r, r), (size - r, r), (r, size - r), (size - r, size - r)):
            if (x < r or x > size - r) and (y < r or y > size - r):
                if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
                    return False
        return True

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            if not in_rounded(x, y):
                buf[idx : idx + 4] = bytes((0, 0, 0, 0))
                continue
            col = BG
            for cx, cy in centers:
                if (x - cx) ** 2 + (y - cy) ** 2 <= dot * dot:
                    col = FG
                    break
            buf[idx : idx + 4] = bytes((col[0], col[1], col[2], 255))
    return png(size, size, bytes(buf))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
    }
    for name, size in targets.items():
        (OUT / name).write_bytes(render(size))
        print(f"wrote {OUT / name} ({size}x{size})")
    (OUT.parent.parent / "dist-icon.png").write_bytes(render(1024))
    print(f"wrote dist-icon.png (1024x1024, source for `pnpm tauri icon`)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
