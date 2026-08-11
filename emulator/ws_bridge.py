#!/usr/bin/env python3
"""WebSocket -> TCP bridge for the Ant Wars emulator.

Browsers can only speak WebSocket, not the raw TCP that the GAME(:9001),
BATTLE(:9002) and COPY(:9003) servers use. This bridge accepts WebSocket
connections and proxies each connection to the matching TCP server.

Frame-level bridging: one WS binary message carries exactly one complete
"IC" protocol frame (9-byte header + body), so the JS client never has to
reassemble a stream.

Paths:
  ws://<host>:8081/game   -> 127.0.0.1:9001
  ws://<host>:8081/battle -> 127.0.0.1:9002
  ws://<host>:8081/copy   -> 127.0.0.1:9003
"""
import asyncio
import os
import struct

from websockets.asyncio.server import serve

MAGIC = b"IC"
HEADER = 9
HOST = os.environ.get("WS_HOST", "127.0.0.1")  # 0.0.0.0 to expose on LAN
PORT = int(os.environ.get("WS_PORT", "8081"))
TARGETS = {"/game": 9001, "/battle": 9002, "/copy": 9003}


def _log(msg):
    print("[ws_bridge] " + msg, flush=True)


async def tcp_to_ws(reader, ws, path):
    try:
        while True:
            header = await reader.readexactly(HEADER)
            if header[0:2] != MAGIC:
                _log("%s tcp->ws non-IC header %s" % (path, header.hex()))
                break
            body_len = struct.unpack_from("<h", header, 6)[0]
            body = await reader.readexactly(body_len) if body_len > 0 else b""
            _log("%s tcp->ws frame len=%d head=%s" % (path, 9 + body_len, header.hex()))
            await ws.send(header + body)  # one full frame per WS message
    except Exception:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def ws_to_tcp(ws, writer, path):
    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                _log("%s ws->tcp frame len=%d head=%s" % (path, len(msg), bytes(msg)[:9].hex()))
                writer.write(bytes(msg))
                await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(ws):
    path = getattr(getattr(ws, "request", None), "path", None) or getattr(ws, "path", "/")
    port = TARGETS.get(path)
    if not port:
        _log("reject unknown path %s" % path)
        await ws.close()
        return
    _log("%s ws connected" % path)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    _log("%s tcp connected" % path)
    await asyncio.gather(tcp_to_ws(reader, ws, path), ws_to_tcp(ws, writer, path))
    _log("%s ws closed" % path)


async def main():
    async with serve(handle, HOST, PORT):
        print("[ws_bridge] ws://%s:%d  {/game,/battle,/copy}" % (HOST, PORT))
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
