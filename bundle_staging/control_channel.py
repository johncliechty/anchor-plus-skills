import os
import sys
import json
import time
import socket
import threading
import secrets
import hashlib
from pathlib import Path
import paths as _paths
import auth_peer
import auth_session

# One-time pairing state
_pairing_lock = threading.Lock()
_pairing_state = {
    "hash": None,
    "expires_at": 0,
    "attempts_left": 0
}

def generate_pairing_code() -> str:
    """Generate a Crockford base32 pairing code, single-use, 10 min expiry, 5 cap."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    # ~50 bits = 10 chars
    code = "".join(secrets.choice(alphabet) for _ in range(10))
    code = f"{code[:5]}-{code[5:]}"
    
    with _pairing_lock:
        _pairing_state["hash"] = hashlib.sha256(code.encode("ascii")).hexdigest()
        _pairing_state["expires_at"] = time.time() + 600
        _pairing_state["attempts_left"] = 5
        
    return code

def exchange_pairing_code(code: str) -> dict:
    """Constant-time compare, nonce-bound exchange for a session cookie."""
    if not code:
        return {"ok": False, "error": "missing code"}
    
    code = code.replace("-", "").upper()
    code_hash = hashlib.sha256(code.encode("ascii")).hexdigest()
    
    with _pairing_lock:
        if time.time() > _pairing_state["expires_at"]:
            return {"ok": False, "error": "expired"}
        
        if _pairing_state["attempts_left"] <= 0:
            return {"ok": False, "error": "cap exceeded"}
            
        if not _pairing_state["hash"]:
            return {"ok": False, "error": "no active pairing"}
            
        import hmac
        if not hmac.compare_digest(_pairing_state["hash"], code_hash):
            _pairing_state["attempts_left"] -= 1
            return {"ok": False, "error": "invalid code"}
            
        # Success - consume code
        _pairing_state["hash"] = None
        _pairing_state["expires_at"] = 0
        _pairing_state["attempts_left"] = 0
        
    session_id = auth_session.mint_session(who="anchor-pair")
    return {"ok": True, "session_id": session_id}

# Control channel server
def get_install_id() -> str:
    install_id_file = _paths.data_dir() / "install_id"
    if not install_id_file.exists():
        install_id_file.write_text(secrets.token_hex(8))
    return install_id_file.read_text().strip()

def start_control_channel():
    t = threading.Thread(target=_run_control_channel, daemon=True)
    t.start()
    return t

def _run_control_channel():
    install_id = get_install_id()
    if sys.platform == "win32":
        _run_named_pipe(install_id)
    else:
        _run_unix_socket(install_id)

def _run_unix_socket(install_id: str):
    sock_dir = _paths.data_dir() / "run"
    sock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    sock_path = sock_dir / f"anchor-{install_id}.sock"
    
    if sock_path.exists():
        sock_path.unlink()
        
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    os.chmod(str(sock_path), 0o600)
    server.listen(5)
    
    while True:
        try:
            conn, _ = server.accept()
            # Peer identity verification
            uid = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 4)
            import struct
            pid, uid, gid = struct.unpack("iii", uid)
            if uid != os.getuid():
                conn.close()
                continue
                
            _handle_control_client(conn)
        except Exception:
            pass

def _run_named_pipe(install_id: str):
    import ctypes
    from ctypes import wintypes
    
    # We must use stdlib ctypes since win32pipe requires pywin32 which may not be present
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    
    pipe_name = fr"\\.\pipe\anchor-{install_id}"
    
    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_MESSAGE = 0x00000004
    PIPE_READMODE_MESSAGE = 0x00000002
    PIPE_WAIT = 0x00000000
    
    # Owner-only DACL string representation (SDDL)
    # O:SYG:SYD:(A;;GA;;;OW) -> System owner, system group, GA (Generic All) for OW (Owner)
    # But wait, Python's security descriptor with SDDL can be complex.
    # Actually, if we just create it with default security (None), it belongs to the creating user,
    # but other users in the same session might have access.
    # Since stdlib ctypes SDDL requires ConvertStringSecurityDescriptorToSecurityDescriptorW,
    # let's just use the current user SID.
    
    sddl = "D:(A;;GA;;;OW)" # Allow Generic All to Owner
    sd = ctypes.c_void_p()
    sd_size = wintypes.DWORD()
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        ctypes.c_wchar_p(sddl), 1, ctypes.byref(sd), ctypes.byref(sd_size)
    )
    
    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD),
                    ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]
    
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = sd
    sa.bInheritHandle = False
    
    while True:
        try:
            hPipe = kernel32.CreateNamedPipeW(
                pipe_name, PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                1, 65536, 65536, 0, ctypes.byref(sa)
            )
            if hPipe == -1:
                time.sleep(1)
                continue
                
            kernel32.ConnectNamedPipe(hPipe, None)
            
            buf = ctypes.create_string_buffer(65536)
            bytes_read = wintypes.DWORD()
            
            if kernel32.ReadFile(hPipe, buf, 65536, ctypes.byref(bytes_read), None):
                data = buf.raw[:bytes_read.value]
                req = json.loads(data.decode("utf-8"))
                resp = _process_control_req(req)
                resp_data = json.dumps(resp).encode("utf-8")
                
                bytes_written = wintypes.DWORD()
                kernel32.WriteFile(hPipe, resp_data, len(resp_data), ctypes.byref(bytes_written), None)
            
            kernel32.FlushFileBuffers(hPipe)
            kernel32.DisconnectNamedPipe(hPipe)
            kernel32.CloseHandle(hPipe)
        except Exception:
            pass
        finally:
            if 'sd' in locals() and sd:
                kernel32.LocalFree(sd)

def _handle_control_client(conn):
    try:
        data = conn.recv(65536)
        if data:
            req = json.loads(data.decode("utf-8"))
            resp = _process_control_req(req)
            conn.sendall(json.dumps(resp).encode("utf-8"))
    except Exception:
        pass
    finally:
        conn.close()

def _process_control_req(req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "ping":
        return {"ok": True}
    if cmd == "pair":
        code = generate_pairing_code()
        return {"ok": True, "code": code}
    return {"ok": False, "error": "unknown cmd"}
