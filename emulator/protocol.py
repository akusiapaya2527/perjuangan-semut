"""IC-framed socket protocol for the Ant Wars client.

Frame layout (9-byte header, little-endian):
  bytes 0-1   "IC"          magic
  bytes 2-3   cmd           uint16 LE
  byte  4     ver           0x01
  byte  5     subver        0x01
  bytes 6-7   bodyLen       uint16 LE  (0 <= bodyLen < 16384-9)
  byte  8     code          0x00
  then        body          little-endian fields

String = uint32(len+1) + utf-8 bytes + trailing NUL byte.
Binary = uint32(len) + bytes.
"""
import struct

MAGIC = b"IC"
HEADER = 9
MAX_BODY = 16384 - HEADER


class Writer:
    __slots__ = ("body",)

    def __init__(self):
        self.body = bytearray()

    def int(self, v):
        self.body += struct.pack("<i", int(v))

    def uint(self, v):
        self.body += struct.pack("<I", int(v))

    def short(self, v):
        self.body += struct.pack("<h", int(v))

    def byte(self, v):
        self.body += struct.pack("<b", int(v))

    def string(self, s):
        b = s.encode("utf-8")
        self.uint(len(b) + 1)
        self.body += b
        self.body += b"\x00"

    def binary(self, data):
        self.body += struct.pack("<I", len(data))
        self.body += data

    def frame(self, cmd, ver=1, subver=1):
        body = bytes(self.body)
        n = len(body)
        if n > MAX_BODY:
            raise ValueError("body too large: %d" % n)
        return MAGIC + struct.pack("<hBB", cmd, ver, subver) + struct.pack("<hB", n, 0) + body


class Reader:
    __slots__ = ("buf", "pos")

    def __init__(self, body: bytes):
        self.buf = body
        self.pos = 0

    def int(self):
        v = struct.unpack_from("<i", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def uint(self):
        v = struct.unpack_from("<I", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def short(self):
        v = struct.unpack_from("<h", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def byte(self):
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def string(self):
        ln = self.uint()
        raw = self.buf[self.pos:self.pos + ln]
        self.pos += ln
        # strip trailing NUL
        if raw.endswith(b"\x00"):
            raw = raw[:-1]
        return raw.decode("utf-8", errors="replace")

    def binary(self):
        ln = self.uint()
        raw = self.buf[self.pos:self.pos + ln]
        self.pos += ln
        return raw

    def readall(self):
        return self.buf

    def done(self):
        return self.pos == len(self.buf)


def parse_header(data: bytes):
    """Return (cmd, ver, subver, bodyLen, code) if a full header is present."""
    if len(data) < HEADER or data[0:2] != MAGIC:
        return None
    cmd = struct.unpack_from("<h", data, 2)[0]
    ver = data[4]
    subver = data[5]
    body_len = struct.unpack_from("<h", data, 6)[0]
    code = data[8]
    if cmd < 0 or cmd >= 32000:
        return None
    if not (0 <= body_len < MAX_BODY):
        return None
    return cmd, ver, subver, body_len, code
