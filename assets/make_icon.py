"""Generate assets/icon.ico (monochrome: a white ball ring on a black rounded square).

Pure Python (no Pillow). Run once: `python assets/make_icon.py`. The .ico is committed, so this
is only needed to change the design.
"""

import math
import struct
import zlib
from pathlib import Path

SIZES = (256, 64, 48, 32, 16)
INK = (11, 11, 11)
PAPER = (247, 247, 245)


def coverage(x, y, size):
    """Colour + alpha of one pixel, from signed distances, anti-aliased by 4x4 supersampling."""
    total = [0.0, 0.0, 0.0, 0.0]
    n = 4
    for sy in range(n):
        for sx in range(n):
            u = (x + (sx + 0.5) / n) / size - 0.5       # -0.5 .. 0.5
            v = (y + (sy + 0.5) / n) / size - 0.5
            # rounded square
            half, radius = 0.5, 0.19
            qx, qy = abs(u) - (half - radius), abs(v) - (half - radius)
            inside = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius <= 0
            if not inside:
                continue
            r = math.hypot(u, v)
            ring = 0.17 <= r <= 0.30
            dot = r <= 0.07
            colour = PAPER if (ring or dot) else INK
            total[0] += colour[0]; total[1] += colour[1]; total[2] += colour[2]; total[3] += 255
    count = n * n
    return tuple(round(t / count) for t in total)


def png(size):
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            r, g, b, a = coverage(x, y, size)
            # the sums above average alpha-weighted colour, so un-weight it for straight alpha
            if a:
                scale = 255 / a
                r, g, b = min(255, round(r * scale)), min(255, round(g * scale)), min(255, round(b * scale))
            row += bytes((r, g, b, a))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    images = [(s, png(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    target = Path(__file__).with_name("icon.ico")
    target.write_bytes(header + entries + blobs)
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
