"""Read-only reproduction of a Windows denied branch-ref read in owned data."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    repo = Path(tempfile.mkdtemp(prefix="anchor-doctor-v6-ref-"))
    commands = [
        ["init", "-b", "master"],
        ["-c", "user.name=Probe", "-c", "user.email=probe@localhost",
         "commit", "--allow-empty", "--no-gpg-sign", "-m", "probe"],
    ]
    for args in commands:
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ref = repo / ".git" / "refs" / "heads" / "master"
    original = ref.read_bytes()
    handle = kernel.CreateFileW(str(ref), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    results = []
    try:
        for args in (["rev-parse", "--verify", "HEAD"],
                     ["rev-list", "--max-count=1", "--all"],
                     ["show-ref", "--verify", "--quiet", "refs/heads/master"]):
            result = subprocess.run(["git", "-C", str(repo), *args],
                                    capture_output=True, text=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            results.append({"args": args, "returncode": result.returncode,
                            "stdout": result.stdout, "stderr": result.stderr})
    finally:
        kernel.CloseHandle(handle)
    assert ref.read_bytes() == original
    print(json.dumps({"repo": str(repo), "commands": results}, indent=2))


if __name__ == "__main__":
    main()
