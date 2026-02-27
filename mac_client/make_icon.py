#!/usr/bin/env python3
"""
Creates the Life Manager app icon — pure Python, no external libraries.
Dark rounded square with blue glow border, matching the dashboard aesthetic.
"""
import struct, zlib, sys, os, math


def _chunk(ctype, data):
    c = ctype + data
    return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)


def _png(pixels, size):
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = _chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
    raw = b''.join(b'\x00' + bytes(c for px in row for c in px) for row in pixels)
    idat = _chunk(b'IDAT', zlib.compress(raw, 9))
    return sig + ihdr + idat + _chunk(b'IEND', b'')


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def create_icon(path, size=512):
    BG      = (13, 17, 23)       # #0d1117
    INNER   = (22, 31, 43)       # slightly lighter
    BORDER  = (88, 166, 255)     # #58a6ff
    GLOW    = (36, 74, 128)      # dim glow

    cx = cy = size / 2
    radius  = size * 0.44        # outer edge of rounded rect
    corner  = size * 0.12        # corner radius
    border  = size * 0.025       # border width
    glow_w  = size * 0.06        # glow fade width

    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            # Signed distance to rounded rectangle
            dx = abs(x - cx) - (radius - corner)
            dy = abs(y - cy) - (radius - corner)
            sdf = (math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0)) - corner

            if sdf > glow_w:
                # Outside glow — background
                row.append(BG)
            elif sdf > 0:
                # Glow halo
                t = sdf / glow_w
                row.append(lerp(GLOW, BG, t))
            elif sdf > -border:
                # Border ring
                t = -sdf / border
                row.append(lerp(BORDER, GLOW, 1 - t))
            else:
                # Inside — subtle radial gradient
                dist_c = math.hypot(x - cx, y - cy) / (size * 0.5)
                row.append(lerp(INNER, BG, dist_c * 0.6))
        pixels.append(row)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(_png(pixels, size))
    print(f"Icon written: {path}")


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'AppIcon.png'
    create_icon(out)
