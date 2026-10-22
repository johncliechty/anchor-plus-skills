"""Continuous local speech dictation engine for Anchor Steward Cockpits, Cave of Wonders & Star Chart.

Supports two complementary local modes:
1. Browser Microphone Capture -> `/api/steward/dictate` (`action: "transcribe"`):
   Captures 16kHz mono PCM WAV chunks directly in the interactive browser session via
   `navigator.mediaDevices.getUserMedia` (bypassing Windows Session 0 service isolation)
   and transcribes them in ~0.35s using local `faster_whisper` (with Windows `System.Speech`
   `SetInputToWaveFile` as zero-dependency fallback).
2. Local Windows `System.Speech` live device session (`action: "start"` / `"poll"` / `"stop"`)
   when running in an interactive desktop process.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
_WHISPER_LOCK = threading.Lock()
_WHISPER_MODEL: Any = None
_WHISPER_LOAD_ERR: str = ""
_PROC: Optional[subprocess.Popen] = None
_ACTIVE: bool = False
_SEQ: int = 0
_CHUNKS: List[Dict[str, Any]] = []
_INTERIM: str = ""
_LAST_POLL_AT: float = 0.0
_LAST_ERROR: str = ""

_HALLUCINATION_PHRASES = {
    "thank you",
    "thank you.",
    "thanks for watching",
    "thanks for watching.",
    "thank you for watching",
    "thank you for watching.",
    "subtitles by the amara.org community",
    "you",
    ".",
    "...",
    "bye.",
}


def _find_hf_cache_root() -> Optional[str]:
    candidates = [
        Path(r"C:\Users\john\.cache\huggingface\hub"),
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    for c in candidates:
        try:
            if c.is_dir():
                return str(c)
        except Exception:
            pass
    return None


def _get_whisper_model() -> Any:
    global _WHISPER_MODEL, _WHISPER_LOAD_ERR
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    with _WHISPER_LOCK:
        if _WHISPER_MODEL is not None:
            return _WHISPER_MODEL
        try:
            from faster_whisper import WhisperModel
            cache_root = _find_hf_cache_root()
            kwargs: Dict[str, Any] = {
                "device": "cpu",
                "compute_type": "int8",
            }
            if cache_root:
                kwargs["download_root"] = cache_root
                for _m_name in ("models--Systran--faster-whisper-small.en", "models--Systran--faster-whisper-base.en", "models--Systran--faster-whisper-base", "models--Systran--faster-whisper-tiny.en", "models--Systran--faster-whisper-tiny"):
                    _c_dir = Path(cache_root) / _m_name / "snapshots"
                    if _c_dir.is_dir():
                        _snaps = sorted([p for p in _c_dir.iterdir() if p.is_dir()])
                        if _snaps:
                            _WHISPER_MODEL = WhisperModel(str(_snaps[-1]), local_files_only=True, **kwargs)
                            return _WHISPER_MODEL
                tiny_dir = Path(cache_root) / "models--Systran--faster-whisper-tiny" / "snapshots"
                if tiny_dir.is_dir():
                    snaps = sorted([p for p in tiny_dir.iterdir() if p.is_dir()])
                    if snaps:
                        _WHISPER_MODEL = WhisperModel(str(snaps[-1]), local_files_only=True, **kwargs)
                        return _WHISPER_MODEL
            _WHISPER_MODEL = WhisperModel("tiny", **kwargs)
            return _WHISPER_MODEL
        except Exception as exc:
            _WHISPER_LOAD_ERR = str(exc)
            return None


def _wav_rms(wav_path: str) -> float:
    try:
        import struct
        import math
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames <= 0:
                return 0.0
            raw = wf.readframes(n_frames)
            if len(raw) < 2:
                return 0.0
            count = len(raw) // 2
            samples = struct.unpack(f"<{count}h", raw[: count * 2])
            if not samples:
                return 0.0
            mean_sq = sum(float(s) * float(s) for s in samples) / float(count)
            return math.sqrt(mean_sq) / 32768.0
    except Exception:
        return 0.05


def _transcribe_wav_via_system_speech(wav_path: str) -> str:
    ps = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {{
    Add-Type -AssemblyName System.Speech
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $grammar = New-Object System.Speech.Recognition.DictationGrammar
    $rec.LoadGrammar($grammar)
    $rec.SetInputToWaveFile('{wav_path.replace("'", "''")}')
    $parts = @()
    while ($true) {{
        $r = $rec.Recognize()
        if (-not $r) {{ break }}
        if ($r.Text) {{ $parts += $r.Text }}
    }}
    $rec.Dispose()
    [Console]::Out.WriteLine(($parts -join ' '))
}} catch {{
    [Console]::Out.WriteLine('')
}}
"""
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=creationflags,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def transcribe_audio(audio_b64: str) -> Dict[str, Any]:
    """Transcribe a base64-encoded 16kHz mono WAV chunk captured by the browser microphone."""
    global _SEQ, _LAST_POLL_AT
    _LAST_POLL_AT = time.time()
    clean_b64 = str(audio_b64 or "").strip()
    if "," in clean_b64 and clean_b64.startswith("data:"):
        clean_b64 = clean_b64.split(",", 1)[1]
    if not clean_b64:
        return {"ok": False, "text": "", "error": "empty audio payload"}
    try:
        wav_bytes = base64.b64decode(clean_b64)
    except Exception as exc:
        return {"ok": False, "text": "", "error": f"invalid base64: {exc}"}
    if len(wav_bytes) < 200:
        return {"ok": True, "text": "", "seq": _SEQ}

    tmp_fd, tmp_path = tempfile.mkstemp(prefix="anchor_dict_", suffix=".wav")
    os.close(tmp_fd)
    try:
        Path(tmp_path).write_bytes(wav_bytes)
        rms = _wav_rms(tmp_path)
        if rms < 0.0025:
            return {"ok": True, "text": "", "rms": round(rms, 5), "seq": _SEQ}

        text = ""
        engine_used = "faster_whisper"
        model = _get_whisper_model()
        if model is not None:
            try:
                segments, _ = model.transcribe(
                    tmp_path,
                    language="en",
                    beam_size=2,
                    best_of=2,
                    initial_prompt="Anchor cockpit, Steward, Foreman, Crucible, Chekhov, deliverables, plan, wave, review.",
                    # best_of=2 set above
                    temperature=0.0,
                    condition_on_previous_text=False,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 250, "speech_pad_ms": 180},
                )
                text = " ".join(s.text.strip() for s in segments if s.text and s.text.strip()).strip()
            except Exception:
                text = ""

        if not text:
            engine_used = "system_speech"
            text = _transcribe_wav_via_system_speech(tmp_path)

        norm_low = text.strip().lower()
        if norm_low in _HALLUCINATION_PHRASES or (len(norm_low) <= 3 and rms < 0.008):
            text = ""

        if text:
            with _LOCK:
                _SEQ += 1
                seq_val = _SEQ
        else:
            seq_val = _SEQ

        return {
            "ok": True,
            "text": text,
            "engine": engine_used,
            "rms": round(rms, 5),
            "seq": seq_val,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    if (-not (Test-Path 'HKCU:\Software\Microsoft\Speech\AudioInput')) {
        New-Item -Path 'HKCU:\Software\Microsoft\Speech\AudioInput' -Force | Out-Null
    }
    if (-not (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Speech\AudioInput' -Name 'DefaultTokenId' -ErrorAction SilentlyContinue)) {
        Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Speech\AudioInput' -Name 'DefaultTokenId' -Value 'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\AudioInput\TokenEnums\MMAudioIn\' -Force
    }
    Add-Type -AssemblyName System.Speech
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $grammar = New-Object System.Speech.Recognition.DictationGrammar
    $rec.LoadGrammar($grammar)
    $rec.SetInputToDefaultAudioDevice()
    $rec.BabbleTimeout = [TimeSpan]::FromSeconds(0)
    $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds(0)
    $rec.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.65)
    $rec.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromSeconds(0.9)

    Register-ObjectEvent -InputObject $rec -EventName SpeechHypothesized -Action {
        $txt = $Event.SourceEventArgs.Result.Text
        if ($txt) {
            $obj = @{ type = 'interim'; text = $txt } | ConvertTo-Json -Compress
            [Console]::Out.WriteLine($obj)
            [Console]::Out.Flush()
        }
    } | Out-Null

    Register-ObjectEvent -InputObject $rec -EventName SpeechRecognized -Action {
        $txt = $Event.SourceEventArgs.Result.Text
        if ($txt) {
            $obj = @{ type = 'final'; text = $txt } | ConvertTo-Json -Compress
            [Console]::Out.WriteLine($obj)
            [Console]::Out.Flush()
        }
    } | Out-Null

    $rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
    $ready = @{ type = 'ready'; status = 'listening' } | ConvertTo-Json -Compress
    [Console]::Out.WriteLine($ready)
    [Console]::Out.Flush()

    while ($true) {
        Start-Sleep -Milliseconds 200
    }
} catch {
    $err = @{ type = 'error'; message = $_.Exception.Message } | ConvertTo-Json -Compress
    [Console]::Out.WriteLine($err)
    [Console]::Out.Flush()
}
"""


def _reader_loop(proc: subprocess.Popen) -> None:
    global _ACTIVE, _SEQ, _INTERIM, _LAST_ERROR
    try:
        stdout = proc.stdout
        if stdout is None:
            return
        for raw_line in stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mtype = msg.get("type")
            if mtype == "interim":
                with _LOCK:
                    _INTERIM = str(msg.get("text") or "").strip()
            elif mtype == "final":
                text = str(msg.get("text") or "").strip()
                if text:
                    with _LOCK:
                        _SEQ += 1
                        _INTERIM = ""
                        _CHUNKS.append({"seq": _SEQ, "text": text, "at": time.time()})
                        if len(_CHUNKS) > 100:
                            del _CHUNKS[:-100]
            elif mtype == "error":
                with _LOCK:
                    _LAST_ERROR = str(msg.get("message") or "speech error")
    except Exception as exc:
        with _LOCK:
            _LAST_ERROR = str(exc)
    finally:
        with _LOCK:
            if _PROC is proc:
                _ACTIVE = False


def _watchdog_loop(proc: subprocess.Popen) -> None:
    global _ACTIVE, _PROC
    while True:
        time.sleep(2.0)
        with _LOCK:
            if _PROC is not proc or not _ACTIVE:
                break
            idle_for = time.time() - _LAST_POLL_AT
            if idle_for > 45.0:
                _ACTIVE = False
                _PROC = None
                try:
                    proc.terminate()
                except Exception:
                    pass
                break


def start_session() -> Dict[str, Any]:
    global _PROC, _ACTIVE, _INTERIM, _LAST_POLL_AT, _LAST_ERROR
    with _LOCK:
        _LAST_POLL_AT = time.time()
        _LAST_ERROR = ""
        if _PROC is not None and _PROC.poll() is None and _ACTIVE:
            return {"ok": True, "active": True, "seq": _SEQ, "last_seq": _SEQ, "interim": _INTERIM}
        if _PROC is not None:
            try:
                _PROC.terminate()
            except Exception:
                pass
            _PROC = None
        _INTERIM = ""
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            _PROC = proc
            _ACTIVE = True
            t_read = threading.Thread(target=_reader_loop, args=(proc,), daemon=True)
            t_read.start()
            t_watch = threading.Thread(target=_watchdog_loop, args=(proc,), daemon=True)
            t_watch.start()
            return {"ok": True, "active": True, "seq": _SEQ, "last_seq": _SEQ, "interim": ""}
        except Exception as exc:
            _ACTIVE = False
            _LAST_ERROR = str(exc)
            return {"ok": False, "active": False, "error": str(exc), "seq": _SEQ}


def stop_session() -> Dict[str, Any]:
    global _PROC, _ACTIVE, _INTERIM
    with _LOCK:
        _ACTIVE = False
        _INTERIM = ""
        proc = _PROC
        _PROC = None
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
    return {"ok": True, "active": False, "seq": _SEQ}


def poll_session(since_seq: int = 0) -> Dict[str, Any]:
    global _LAST_POLL_AT
    with _LOCK:
        _LAST_POLL_AT = time.time()
        alive = bool(_PROC is not None and _PROC.poll() is None and _ACTIVE)
        new_chunks = [c for c in _CHUNKS if int(c.get("seq", 0)) > since_seq]
        return {
            "ok": True,
            "active": alive,
            "seq": _SEQ,
            "chunks": new_chunks,
            "interim": _INTERIM if alive else "",
            "error": _LAST_ERROR,
        }
