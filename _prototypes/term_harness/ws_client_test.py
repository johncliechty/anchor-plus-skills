"""Minimal stdlib WebSocket client — proves the harness end-to-end without a browser.
Connects to /ws?target=shell, reads the banner, sends a command, reads the echo+output.
"""
import socket, base64, struct, os, time, sys

PORT = 8799
def mask(data):
    import os as _o
    m = _o.urandom(4)
    return m + bytes(b ^ m[i % 4] for i, b in enumerate(data))

def send_text(sock, s):
    data = s.encode("utf-8")
    hdr = bytearray([0x81])              # FIN + text
    n = len(data)
    if n < 126: hdr.append(0x80 | n)
    else: hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
    sock.sendall(bytes(hdr) + mask(data))

def recv_frame(sock):
    h = sock.recv(2)
    if len(h) < 2: return None
    ln = h[1] & 0x7F
    if ln == 126: ln = struct.unpack(">H", sock.recv(2))[0]
    elif ln == 127: ln = struct.unpack(">Q", sock.recv(8))[0]
    data = b""
    while len(data) < ln:
        c = sock.recv(ln - len(data))
        if not c: break
        data += c
    return (h[0] & 0x0F, data)

def drain(sock, seconds):
    sock.settimeout(0.4); out = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            f = recv_frame(sock)
        except socket.timeout:
            continue
        except Exception:
            break
        if f is None: break
        op, data = f
        if op == 0x8: out.append("[ws close]"); break
        out.append(data.decode("utf-8", "replace"))
    return "".join(out)

def main():
    s = socket.create_connection(("127.0.0.1", PORT))
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET /ws?target=shell HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    # read handshake response headers
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(256)
    print("HANDSHAKE:", buf.split(b"\r\n")[0].decode())
    print("101 upgrade:", b"101" in buf.split(b"\r\n")[0])
    banner = drain(s, 2.5)
    print(f"\n--- banner ({len(banner)} chars) ---\n{banner[:400]}")
    send_text(s, "echo WS_BRIDGE_OK\r\n")
    resp = drain(s, 2.5)
    print(f"\n--- after 'echo WS_BRIDGE_OK' ({len(resp)} chars) ---\n{resp[-600:]}")
    print("\nRESULT:", "PASS - WS_BRIDGE_OK echoed back" if "WS_BRIDGE_OK" in (banner+resp) else "see output above")
    s.close()

if __name__ == "__main__":
    main()
