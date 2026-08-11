"""Minimal pure-stdlib PNG decode/encode (no Pillow)."""
import struct
import zlib


class PngError(Exception):
    pass


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png(data):
    """Return (width, height, bytes) of 8-bit RGBA scanlines (filter removed)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError("bad signature")
    pos = 8
    w = h = bitdepth = colortype = None
    idat = b""
    palette = b""
    trns = b""
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if ctype == b"IHDR":
            w, h, bitdepth, colortype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunk)
            if interlace:
                raise PngError("interlaced PNG unsupported")
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + ln
    if w is None or h is None:
        raise PngError("no IHDR")
    if bitdepth != 8:
        raise PngError("bit depth %d unsupported" % bitdepth)
    raw = zlib.decompress(idat)
    return _unfilter(w, h, colortype, raw, palette, trns)


def _bpp(colortype):
    return {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colortype)


def _unfilter(w, h, colortype, raw, palette, trns):
    bpp = _bpp(colortype)
    if bpp is None:
        raise PngError("color type %d unsupported" % colortype)
    stride = w * bpp
    out = bytearray()
    prev = bytearray(stride)
    off = 0
    for _ in range(h):
        f = raw[off]
        off += 1
        row = bytearray(raw[off:off + stride])
        off += stride
        for i in range(stride):
            x = row[i]
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                x = (x + a) & 0xFF
            elif f == 2:
                x = (x + b) & 0xFF
            elif f == 3:
                x = (x + ((a + b) >> 1)) & 0xFF
            elif f == 4:
                x = (x + _paeth(a, b, c)) & 0xFF
            elif f != 0:
                raise PngError("bad filter %d" % f)
            row[i] = x
        out += row
        prev = row
    return _to_rgba(colortype, w, h, bytes(out), palette, trns)


def _to_rgba(colortype, w, h, data, palette, trns):
    if colortype == 6:
        return w, h, data
    if colortype == 2:
        return w, h, _expand(w, h, 3, data, lambda p: p + b"\xff")
    if colortype == 0:
        return w, h, _expand(w, h, 1, data, lambda p: p * 3 + b"\xff")
    if colortype == 4:
        return w, h, _expand(w, h, 2, data, lambda p: p[:1] * 3 + p[1:2])
    if colortype == 3:
        rgba = bytearray()
        trns_len = len(trns)
        for i in range(w * h):
            idx = data[i]
            if idx * 3 + 2 < len(palette):
                r, g, b = palette[idx * 3:idx * 3 + 3]
                a = trns[idx] if idx < trns_len else 255
                rgba += bytes((r, g, b, a))
            else:
                rgba += b"\x00\x00\x00\x00"
        return w, h, bytes(rgba)
    raise PngError("color type %d unsupported" % colortype)


def _expand(w, h, bpp, data, conv):
    out = bytearray()
    stride = w * bpp
    for y in range(h):
        row = data[y * stride:(y + 1) * stride]
        for x in range(w):
            out += conv(row[x * bpp:(x + 1) * bpp])
    return bytes(out)


def crop(rgba, w, x, y, cw, ch):
    """Crop RGBA w-wide image to rect (x,y,cw,ch); clamps to bounds."""
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    if x + cw > w:
        cw = w - x
    if cw <= 0 or ch <= 0:
        cw = max(cw, 1)
        ch = max(ch, 1)
    rows = []
    for yy in range(ch):
        src = (y + yy) * w * 4 + x * 4
        rows.append(rgba[src:src + cw * 4])
    return b"".join(rows)


def encode_png(w, h, rgba):
    """Encode 8-bit RGBA PNG (filter 0)."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw += b"\x00" + rgba[y * stride:(y + 1) * stride]
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
