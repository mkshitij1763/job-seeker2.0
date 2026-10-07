"""Generate the home-screen icons (run once; the PNGs are committed). A white briefcase on the accent blue."""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "jobseeker" / "web" / "static"
BLUE, WHITE = (37, 99, 235), (255, 255, 255)


def pixel(x: int, y: int, n: int) -> tuple[int, int, int]:
    u, v = x / n, y / n
    body = 0.22 <= u <= 0.78 and 0.36 <= v <= 0.76
    inner = 0.27 <= u <= 0.73 and 0.41 <= v <= 0.71
    handle = 0.39 <= u <= 0.61 and 0.26 <= v <= 0.37 and not (0.44 <= u <= 0.56 and v >= 0.31)
    clasp = 0.46 <= u <= 0.54 and 0.50 <= v <= 0.58
    return WHITE if (body and not inner) or handle or clasp else BLUE


def png(n: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for x in range(n) for c in pixel(x, y, n)) for y in range(n))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    for size in (180, 512):
        (OUT / f"icon-{size}.png").write_bytes(png(size))
        print("wrote", size)
