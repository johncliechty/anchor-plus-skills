import os
import sys
import socket

def check_same_user_tcp(client_port: int) -> bool:
    """
    Check if the TCP loopback peer on `client_port` is owned by the same OS user
    as the current process. Fails closed (False) if unavailable/ambiguous.
    """
    try:
        if sys.platform == "win32":
            return _check_same_user_win32(client_port)
        elif sys.platform.startswith("linux"):
            uid = _get_linux_peer_uid(client_port)
            return uid is not None and uid == os.getuid()
        elif sys.platform == "darwin":
            uid = _get_macos_peer_uid(client_port)
            return uid is not None and uid == os.getuid()
        else:
            return False
    except Exception:
        return False

def _check_same_user_win32(client_port: int) -> bool:
    import ctypes
    from ctypes import wintypes
    
    iphlpapi = ctypes.windll.iphlpapi
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    
    TCP_TABLE_OWNER_PID_ALL = 5
    
    class MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]
        
    size = wintypes.DWORD(0)
    # 2 = AF_INET
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, TCP_TABLE_OWNER_PID_ALL, 0)
    
    buf = ctypes.create_string_buffer(size.value)
    res = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, TCP_TABLE_OWNER_PID_ALL, 0)
    if res != 0:
        return False
        
    num_entries = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    
    offset = ctypes.sizeof(wintypes.DWORD)
    row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
    
    target_pid = None
    for _ in range(num_entries):
        row = MIB_TCPROW_OWNER_PID.from_buffer_copy(buf[offset:offset+row_size])
        offset += row_size
        if socket.ntohs(row.dwLocalPort) == client_port:
            target_pid = row.dwOwningPid
            break
            
    if target_pid is None:
        return False
        
    PROCESS_QUERY_INFORMATION = 0x0400
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, target_pid)
    if not h_proc:
        return False
        
    TOKEN_QUERY = 0x0008
    h_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(h_proc, TOKEN_QUERY, ctypes.byref(h_token)):
        kernel32.CloseHandle(h_proc)
        return False
        
    h_current_proc = kernel32.GetCurrentProcess()
    h_current_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(h_current_proc, TOKEN_QUERY, ctypes.byref(h_current_token)):
        kernel32.CloseHandle(h_token)
        kernel32.CloseHandle(h_proc)
        return False

    def get_token_user_sid(h_t):
        TokenUser = 1
        sz = wintypes.DWORD(0)
        advapi32.GetTokenInformation(h_t, TokenUser, None, 0, ctypes.byref(sz))
        if sz.value == 0:
            return None
        b = ctypes.create_string_buffer(sz.value)
        if not advapi32.GetTokenInformation(h_t, TokenUser, b, sz.value, ctypes.byref(sz)):
            return None
            
        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("Sid", ctypes.c_void_p),
                ("Attributes", wintypes.DWORD)
            ]
        class TOKEN_USER(ctypes.Structure):
            _fields_ = [
                ("User", SID_AND_ATTRIBUTES)
            ]
        tu = ctypes.cast(b, ctypes.POINTER(TOKEN_USER)).contents
        return tu.User.Sid

    sid1 = get_token_user_sid(h_token)
    sid2 = get_token_user_sid(h_current_token)
    
    is_same = False
    if sid1 and sid2:
        is_same = bool(advapi32.EqualSid(sid1, sid2))
        
    kernel32.CloseHandle(h_current_token)
    kernel32.CloseHandle(h_token)
    kernel32.CloseHandle(h_proc)
    
    return is_same

def _get_linux_peer_uid(client_port: int) -> int | None:
    import glob
    inode = None
    client_hex_port = f"{client_port:04X}"
    for netfile in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(netfile) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10 or parts[0] == "sl": continue
                    local_ip, local_port = parts[1].split(':')
                    if local_port == client_hex_port:
                        inode = parts[9]
                        break
        except FileNotFoundError:
            continue
        if inode:
            break
            
    if not inode:
        return None
        
    for fd_dir in glob.glob("/proc/[0-9]*/fd"):
        try:
            for fd in os.listdir(fd_dir):
                link = os.readlink(os.path.join(fd_dir, fd))
                if link == f"socket:[{inode}]":
                    return os.stat(fd_dir).st_uid
        except (OSError, ValueError):
            continue
            
    return None

def _get_macos_peer_uid(client_port: int) -> int | None:
    import subprocess
    try:
        # lsof format: COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
        out = subprocess.run(["lsof", "-n", "-P", "-i", f"TCP:{client_port}"], 
                             capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) > 8 and parts[2].isdigit():
                return int(parts[2])
    except Exception:
        pass
    return None
