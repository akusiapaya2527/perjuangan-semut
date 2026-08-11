#!/usr/bin/env python3
"""Browser bridge for Perjuangan Semut.

Relays the ADL game window (captured by bridge/streamer via ScreenCaptureKit)
into a browser tab as MJPEG, and forwards pointer/keyboard input from the page
back to the game via CGEvent.

Ports:
  8095  HTTP  -> control page (/), MJPEG stream (/stream), WebSocket (/ws)
  8096  TCP   <- bridge/streamer pushes length-prefixed JPEG frames here
  8097  TCP   -> bridge/streamer input server (line protocol)

Override any port via env: WEBBRIDGE_HTTP, WEBBRIDGE_VIDEO, WEBBRIDGE_INPUT.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_PORT = int(os.environ.get("WEBBRIDGE_HTTP", "8095"))
VIDEO_PORT = int(os.environ.get("WEBBRIDGE_VIDEO", "8096"))
INPUT_PORT = int(os.environ.get("WEBBRIDGE_INPUT", "8097"))

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FrameHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.data = None
        self.version = 0

    def update(self, data):
        with self.lock:
            self.data = data
            self.version += 1
        self.event.set()

    def latest(self):
        with self.lock:
            return self.data, self.version


hub = FrameHub()


def recv_exact(sock, n):
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            return None
        out += chunk
    return out


def video_loop():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", VIDEO_PORT))
        srv.listen(1)
        print(f"[webbridge] video listener on :{VIDEO_PORT}")
        while True:
            conn, _ = srv.accept()
            print("[webbridge] streamer connected")
            try:
                while True:
                    hdr = recv_exact(conn, 4)
                    if hdr is None:
                        break
                    ln = struct.unpack(">I", hdr)[0]
                    if ln <= 0 or ln > 4 * 1024 * 1024:
                        break
                    data = recv_exact(conn, ln)
                    if data is None:
                        break
                    hub.update(data)
            except OSError:
                pass
            finally:
                conn.close()
                print("[webbridge] streamer disconnected, waiting...")


class InputLink:
    def __init__(self, port):
        self.port = port
        self.sock = None
        self.lock = threading.Lock()

    def _connect(self):
        while True:
            try:
                s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
                self.sock = s
                print(f"[webbridge] input link up :{self.port}")
                return
            except OSError:
                self.sock = None
                time.sleep(1)

    def warm(self):
        while True:
            with self.lock:
                if self.sock is None:
                    self._connect()
            time.sleep(5)

    def send(self, line):
        with self.lock:
            try:
                if self.sock is None:
                    self._connect()
                self.sock.sendall((line + "\n").encode())
            except OSError:
                if self.sock is not None:
                    try:
                        self.sock.close()
                    except OSError:
                        pass
                self.sock = None


input_link = InputLink(INPUT_PORT)


def send_ws(conn, opcode, payload=b""):
    header = bytearray([0x80 | opcode])
    ln = len(payload)
    if ln < 126:
        header.append(ln)
    elif ln < 65536:
        header.append(126)
        header += ln.to_bytes(2, "big")
    else:
        header.append(127)
        header += ln.to_bytes(8, "big")
    conn.sendall(bytes(header) + payload)


def read_ws_frame(rfile):
    hdr = rfile.read(2)
    if len(hdr) < 2:
        return None
    b0, b1 = hdr[0], hdr[1]
    opcode = b0 & 0x0F
    masked = (b1 >> 7) & 1
    ln = b1 & 0x7F
    if ln == 126:
        e = rfile.read(2)
        if len(e) < 2:
            return None
        ln = int.from_bytes(e, "big")
    elif ln == 127:
        e = rfile.read(8)
        if len(e) < 8:
            return None
        ln = int.from_bytes(e, "big")
    mask = rfile.read(4) if masked else None
    payload = b""
    while len(payload) < ln:
        chunk = rfile.read(ln - len(payload))
        if not chunk:
            break
        payload += chunk
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def handle_command(msg):
    t = msg.get("t")
    if t == "move":
        input_link.send(f"MOVE {msg['x']} {msg['y']}")
    elif t == "down":
        input_link.send(f"DOWN {msg['x']} {msg['y']} {msg.get('b', 0)}")
    elif t == "up":
        input_link.send(f"UP {msg['x']} {msg['y']} {msg.get('b', 0)}")
    elif t == "key":
        input_link.send(f"KEY {msg['c']} {msg.get('d', 1)}")


def ws_loop(conn, rfile):
    try:
        while True:
            frame = read_ws_frame(rfile)
            if frame is None:
                break
            opcode, payload = frame
            if opcode == 0x8:  # close
                send_ws(conn, 0x8, payload)
                break
            if opcode == 0x9:  # ping
                send_ws(conn, 0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x1:  # text
                try:
                    msg = json.loads(payload.decode("utf-8"))
                    handle_command(msg)
                except (ValueError, KeyError):
                    pass
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _page(self):
        try:
            with open(__file__.replace(".py", ".html"), "rb") as f:
                return f.read()
        except OSError:
            return b"<h1>webbridge.html missing</h1>"

    def do_GET(self):
        if self.path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/stream":
            self.stream_mjpeg()
            return
        if self.path == "/ws":
            self.upgrade_ws()
            return
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        body = self._page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def stream_mjpeg(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        seen = 0
        try:
            while True:
                hub.event.wait(timeout=1.0)
                if hub.event.is_set():
                    hub.event.clear()
                data, ver = hub.latest()
                if ver != seen and data:
                    seen = ver
                    head = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                    )
                    self.wfile.write(head + data + b"\r\n")
                    self.wfile.flush()
        except (OSError, BrokenPipeError):
            pass

    def upgrade_ws(self):
        key = None
        while True:
            line = self.rfile.readline().strip()
            if not line:
                break
            if line.lower().startswith(b"sec-websocket-key:"):
                key = line.split(b":", 1)[1].strip().decode()
        if not key:
            self.send_response(400)
            self.end_headers()
            return
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()
        ).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        ws_loop(self.connection, self.rfile)


def main():
    threading.Thread(target=video_loop, daemon=True).start()
    threading.Thread(target=input_link.warm, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    srv.daemon_threads = True
    print(f"[webbridge] http://127.0.0.1:{HTTP_PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
