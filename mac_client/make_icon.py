#!/usr/bin/env python3
"""
Creates the Life Manager app icon — pure Python, no external libraries.
Dark rounded square with blue glow border and activity-bar chart inside.
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
    BG     = (13, 17, 23)      # #0d1117 — outer background
    INNER  = (22, 31, 43)      # inner fill
    BORDER = (88, 166, 255)    # #58a6ff — blue border
    GLOW   = (36, 74, 128)     # dim glow
    BAR_HI = (88, 166, 255)    # bar top (bright blue)
    BAR_LO = (30, 60, 120)     # bar bottom (dim blue)

    cx = cy = size / 2
    radius = size * 0.44
    corner = size * 0.12
    border = size * 0.025
    glow_w = size * 0.06

    # Activity bars: 4 bars of varying height
    bar_count = 4
    bar_w = size * 0.09
    bar_gap = size * 0.03
    total_w = bar_count * bar_w + (bar_count - 1) * bar_gap
    bar_x0 = cx - total_w / 2
    bar_base = cy + size * 0.16      # bottom edge of all bars
    max_bar_h = size * 0.36
    bar_heights = [0.38, 0.72, 0.52, 0.90]  # tallest last — ascending feel

    # Precompute bar rects: (x1, y1, x2, y2)
    bar_rects = []
    for i, h in enumerate(bar_heights):
        bx1 = bar_x0 + i * (bar_w + bar_gap)
        bx2 = bx1 + bar_w
        by2 = bar_base
        by1 = bar_base - h * max_bar_h
        bar_rects.append((bx1, by1, bx2, by2))

    def bar_color(px, py):
        """Returns bar color if (px,py) is inside any bar, else None."""
        for bx1, by1, bx2, by2 in bar_rects:
            if bx1 <= px < bx2 and by1 <= py <= by2:
                t = (py - by1) / max(by2 - by1, 1)  # 0=top bright, 1=base dim
                return lerp(BAR_HI, BAR_LO, t * 0.75)
        return None

    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            # Signed distance to rounded rectangle
            dx = abs(x - cx) - (radius - corner)
            dy = abs(y - cy) - (radius - corner)
            sdf = (math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0)) - corner

            if sdf > glow_w:
                row.append(BG)
            elif sdf > 0:
                t = sdf / glow_w
                row.append(lerp(GLOW, BG, t))
            elif sdf > -border:
                t = -sdf / border
                row.append(lerp(BORDER, GLOW, 1 - t))
            else:
                # Inside the rounded rect — check bars first
                bc = bar_color(x, y)
                if bc is not None:
                    row.append(bc)
                else:
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
