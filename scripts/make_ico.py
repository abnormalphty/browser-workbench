#!/usr/bin/env python3
"""Pack square PNG renders of the app icon into a Windows .ico (PNG entries, Windows Vista and later).
Usage: make_ico.py OUT.ico IN.png [IN.png ...]   (each at most 256 px)
"""
import struct
import sys
from pathlib import Path

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def main(out, *inputs):
    images = [Path(name).read_bytes() for name in inputs]
    entries, data = [], b''
    offset = 6 + 16 * len(images)
    for png in images:
        if png[:8] != PNG_SIGNATURE:
            raise SystemExit(f'not a PNG: {inputs[images.index(png)]}')
        width, height = struct.unpack('>II', png[16:24])  # IHDR
        if width != height or width > 256:
            raise SystemExit(f'icon images must be square and at most 256 px, got {width}x{height}')
        # A size of 0 means 256; 1 plane, 32 bits per pixel.
        entries.append(struct.pack('<BBBBHHII', width % 256, height % 256, 0, 0, 1, 32, len(png), offset + len(data)))
        data += png
    Path(out).write_bytes(struct.pack('<HHH', 0, 1, len(images)) + b''.join(entries) + data)


if __name__ == '__main__':
    main(*sys.argv[1:])
