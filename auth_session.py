import json
import time
import secrets
import os
import threading
from pathlib import Path
import paths as _paths

IDLE_EXPIRY = 86400  # 1 day
ABSOLUTE_EXPIRY = 7 * 86400  # 7 days

def _session_store_path() -> Path:
    return _paths.data_dir() / "sessions.json"

def _load_sessions() -> dict:
    try:
        with _paths.WRITE_LOCK:
            if _session_store_path().exists():
                return json.loads(_session_store_path().read_text())
    except Exception:
        pass
    return {}

def _save_sessions(data: dict):
    with _paths.WRITE_LOCK:
        _session_store_path().write_text(json.dumps(data))

def mint_session(who: str = "unknown") -> str:
    sessions = _load_sessions()
    session_id = secrets.token_urlsafe(32)
    now = time.time()
    sessions[session_id] = {
        "created": now,
        "last_active": now,
        "who": who,
        "bypassPermissions": False
    }
    _save_sessions(sessions)
    return session_id

def validate_session(session_id: str) -> bool:
    if not session_id:
        return False
    sessions = _load_sessions()
    now = time.time()
    sess = sessions.get(session_id)
    if not sess:
        return False
        
    if now - sess["created"] > ABSOLUTE_EXPIRY:
        return False
    if now - sess["last_active"] > IDLE_EXPIRY:
        return False
        
    sess["last_active"] = now
    _save_sessions(sessions)
    return True

def invalidate_all():
    _save_sessions({})
    
def get_session(session_id: str) -> dict | None:
    sessions = _load_sessions()
    return sessions.get(session_id)
    
def enable_bypass(session_id: str):
    sessions = _load_sessions()
    if session_id in sessions:
        sessions[session_id]["bypassPermissions"] = True
        _save_sessions(sessions)

# ── Armed Claim Window (server-memory only) ──────────────────────────────
_claim_lock = threading.Lock()
_claim_state = {
    "armed_until": 0.0,
    "nonce": None
}

def arm_claim() -> str:
    with _claim_lock:
        _claim_state["armed_until"] = time.time() + 60.0
        _claim_state["nonce"] = secrets.token_hex(16)
        return _claim_state["nonce"]

def is_claim_armed() -> bool:
    with _claim_lock:
        return time.time() < _claim_state["armed_until"]

def get_claim_nonce() -> str | None:
    with _claim_lock:
        if time.time() < _claim_state["armed_until"]:
            return _claim_state["nonce"]
        return None

def consume_claim(nonce: str) -> bool:
    with _claim_lock:
        if time.time() < _claim_state["armed_until"] and nonce and nonce == _claim_state["nonce"]:
            _claim_state["armed_until"] = 0.0
            _claim_state["nonce"] = None
            return True
        return False
