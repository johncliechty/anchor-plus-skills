"""Fast native Windows 11 spellcheck engine for Anchor Steward dialogues.

Uses the OS native ISpellCheckerFactory COM interface (MsSpellCheckFacility.dll,
the exact engine that WebView2 uses to draw red underlines) via ctypes, with a
thread-local COM instance, in-memory LRU cache, and persistent custom dictionary
(~/.anchor/custom_dictionary.txt).
"""
import ctypes
from ctypes import wintypes
import difflib
from pathlib import Path
import re
import threading

_TLS = threading.local()
_LOCK = threading.Lock()
_WORD_CACHE = {}

_DEFAULT_ALLOW = {
    "anchor", "aladdin", "steward", "stewards", "crucible", "foreman",
    "gandalf", "anvil", "aegis", "chekhov", "ramanujan", "superjump",
    "jumper", "ecgberht", "tailscale", "mothership", "cockpit", "cockpits",
    "worktree", "worktrees", "playwright", "pytest", "subagent", "subagents",
    "deliverable", "deliverables", "markdown", "docx", "pptx", "xlsx",
    "pdf", "html", "json", "jsonl", "cli", "gui", "api", "llm", "llms",
    "claude", "gemini", "chatgpt", "grok", "fable", "argon", "sonnet",
    "opus", "haiku", "webview", "webview2", "nssm", "github", "git",
    "roadmap", "grasscatch", "grasscatcher", "boneyard", "trio", "foundry",
}

_CUSTOM_DICT_PATH = Path.home() / ".anchor" / "custom_dictionary.txt"
_CUSTOM_WORDS = set(_DEFAULT_ALLOW)


def _load_custom_words():
    with _LOCK:
        try:
            if _CUSTOM_DICT_PATH.is_file():
                for line in _CUSTOM_DICT_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                    w = line.strip().lower()
                    if w:
                        _CUSTOM_WORDS.add(w)
        except OSError:
            pass


_load_custom_words()


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, guid_str: str):
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid_str), ctypes.byref(self))


def _get_thread_checker():
    checker = getattr(_TLS, "checker", None)
    if checker is not None:
        return checker
    try:
        ole32 = ctypes.oledll.ole32
        ole32.CoInitialize(None)
        clsid = _GUID("{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}")
        iid = _GUID("{8E018A9D-2415-4677-BF08-794EA61F94BB}")
        factory = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(factory)
        )
        if hr != 0 or not factory.value:
            _TLS.checker = False
            return False
        fv = ctypes.cast(
            ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        create_fn = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
        )(fv[5])
        chk = ctypes.c_void_p()
        hr2 = create_fn(factory, "en-US", ctypes.byref(chk))
        # Release factory
        rel_fn = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(fv[2])
        rel_fn(factory)
        if hr2 != 0 or not chk.value:
            _TLS.checker = False
            return False
        _TLS.checker = chk
        return chk
    except Exception:
        _TLS.checker = False
        return False


def _release_com(ptr: ctypes.c_void_p):
    if not ptr or not ptr.value:
        return
    try:
        vt = ctypes.cast(
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        rel = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vt[2])
        rel(ptr)
    except Exception:
        pass


def _apply_casing(original: str, suggestion: str) -> str:
    if not original or not suggestion:
        return suggestion
    if original.isupper() and len(original) > 1:
        return suggestion.upper()
    if original[0].isupper() and original[1:].islower():
        return suggestion[0].upper() + suggestion[1:]
    return suggestion


def check_word(word: str) -> dict:
    """Check a single word and return top ranked replacement suggestions if misspelled."""
    raw = str(word or "").strip()
    clean = re.sub(r"^[^A-Za-z']+|[^A-Za-z']+$", "", raw)
    if len(clean) <= 1 or any(ch.isdigit() for ch in clean):
        return {"ok": True, "word": clean or raw, "misspelled": False, "correct": True, "suggestions": []}
    low = clean.lower()
    if low in _CUSTOM_WORDS:
        return {"ok": True, "word": clean, "misspelled": False, "correct": True, "suggestions": []}
    with _LOCK:
        cached = _WORD_CACHE.get(clean)
    if cached is not None:
        return {
            "ok": True,
            "word": clean,
            "misspelled": cached["misspelled"],
            "correct": not cached["misspelled"],
            "suggestions": list(cached["suggestions"]),
        }

    chk = _get_thread_checker()
    if not chk:
        # Fallback when COM spellchecker is unavailable
        sugs = [
            _apply_casing(clean, m)
            for m in difflib.get_close_matches(low, list(_CUSTOM_WORDS), n=5, cutoff=0.72)
        ]
        return {"ok": True, "word": clean, "misspelled": bool(sugs), "correct": not bool(sugs), "suggestions": sugs}

    try:
        cv = ctypes.cast(
            ctypes.cast(chk, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        check_fn = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
        )(cv[4])
        suggest_fn = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
        )(cv[5])

        enum_err = ctypes.c_void_p()
        hr = check_fn(chk, clean, ctypes.byref(enum_err))
        has_err = False
        if hr == 0 and enum_err.value:
            ev = ctypes.cast(
                ctypes.cast(enum_err, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            next_err = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            )(ev[3])
            err_ptr = ctypes.c_void_p()
            if next_err(enum_err, ctypes.byref(err_ptr)) == 0 and err_ptr.value:
                has_err = True
                _release_com(err_ptr)
            _release_com(enum_err)

        sugs = []
        if has_err:
            enum_str = ctypes.c_void_p()
            if suggest_fn(chk, clean, ctypes.byref(enum_str)) == 0 and enum_str.value:
                sv = ctypes.cast(
                    ctypes.cast(enum_str, ctypes.POINTER(ctypes.c_void_p))[0],
                    ctypes.POINTER(ctypes.c_void_p),
                )
                next_str = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    wintypes.ULONG,
                    ctypes.POINTER(ctypes.c_void_p),
                    ctypes.POINTER(wintypes.ULONG),
                )(sv[3])
                for _ in range(6):
                    raw_ptr = ctypes.c_void_p()
                    fetched = wintypes.ULONG(0)
                    r = next_str(enum_str, 1, ctypes.byref(raw_ptr), ctypes.byref(fetched))
                    if r != 0 or not fetched.value or not raw_ptr.value:
                        break
                    val = ctypes.wstring_at(raw_ptr.value)
                    ctypes.oledll.ole32.CoTaskMemFree(raw_ptr)
                    if val:
                        cased = _apply_casing(clean, val)
                        if cased not in sugs:
                            sugs.append(cased)
                _release_com(enum_str)

        res = {"misspelled": has_err, "suggestions": sugs}
        with _LOCK:
            if len(_WORD_CACHE) > 4000:
                _WORD_CACHE.clear()
            _WORD_CACHE[clean] = res
        return {"ok": True, "word": clean, "misspelled": has_err, "correct": not has_err, "suggestions": sugs}
    except Exception:
        return {"ok": True, "word": clean, "misspelled": False, "correct": True, "suggestions": []}


def check_text(text: str) -> dict:
    """Scan all words in text and return misspelled spans with suggestions."""
    s = str(text or "")
    errors = []
    seen = {}
    for m in re.finditer(r"[A-Za-z][A-Za-z']*[A-Za-z]|[A-Za-z]{2,}", s):
        w = m.group(0)
        info = seen.get(w)
        if info is None:
            info = check_word(w)
            seen[w] = info
        if info.get("misspelled"):
            errors.append({
                "word": w,
                "start": m.start(),
                "end": m.end(),
                "suggestions": info.get("suggestions") or [],
            })
    return {"ok": True, "errors": errors}


def add_word(word: str) -> dict:
    """Add a word to the custom dictionary and OS spellchecker."""
    clean = re.sub(r"^[^A-Za-z']+|[^A-Za-z']+$", "", str(word or "").strip())
    if not clean:
        return {"ok": False, "error": "empty word"}
    low = clean.lower()
    with _LOCK:
        _CUSTOM_WORDS.add(low)
        _WORD_CACHE.pop(clean, None)
        _WORD_CACHE.pop(low, None)
        _WORD_CACHE.pop(clean.capitalize(), None)
        try:
            _CUSTOM_DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _CUSTOM_DICT_PATH.open("a", encoding="utf-8") as f:
                f.write(low + "\n")
        except OSError:
            pass
    chk = _get_thread_checker()
    if chk:
        try:
            cv = ctypes.cast(
                ctypes.cast(chk, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            add_fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p)(cv[6])
            add_fn(chk, clean)
        except Exception:
            pass
    return {"ok": True, "word": clean}
