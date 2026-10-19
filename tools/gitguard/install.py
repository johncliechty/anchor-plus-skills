"""Build this machine's gitguard launchers (Grok code R2 N1, N2).

A real ``git.exe`` (distlib's console launcher, the same mechanism pip uses for its console scripts) that runs
gitguard with Python and forwards the original argument vector untouched (no cmd reparsing of carets, quotes or
newlines), plus a ``git`` sh script and a BASH_ENV file for Git Bash, which otherwise puts /mingw64/bin first.
The launcher embeds this machine's Python path, so it is built here, not shipped: under
%LOCALAPPDATA%/anchor-gitguard/bin, rebuilt when gitguard.py changes. ``ensure()`` returns (bin_dir, bash_env) or
("", "") when it could not be built (the caller then falls back to the plain directory with git.cmd).
"""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _bin_dir():
    base = os.environ.get("ANCHOR_GITGUARD_DIR") or os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home()), "anchor-gitguard")
    return Path(base) / "bin"


def _posix(p):
    s = str(p).replace("\\", "/")
    return ("/" + s[0].lower() + s[2:]) if len(s) > 1 and s[1] == ":" else s


def ensure():
    src = HERE / "gitguard.py"
    try:
        code = src.read_bytes()
        stamp = hashlib.sha1(code + sys.executable.encode()).hexdigest()[:12]
        out = _bin_dir()
        mark = out / ".stamp"
        exe = out / "git.exe"
        if exe.exists() and mark.exists() and mark.read_text(encoding="utf-8").strip() == stamp:
            return str(out), str(out / "bash_env.sh")
        out.mkdir(parents=True, exist_ok=True)
        from pip._vendor.distlib.scripts import ScriptMaker
        (out / "gitguard_impl.py").write_bytes(code)      # the guard itself, beside its launcher
        maker = ScriptMaker(None, str(out), add_launchers=True)
        maker.executable = sys.executable
        maker.variants = {""}
        maker.clobber = True
        # the launcher's script: put this directory on sys.path, then run the guard with the untouched argv
        maker.script_template = ("# -*- coding: utf-8 -*-\nimport sys, os\n"
                                 "sys.path.insert(0, %r)\n"
                                 "from gitguard_impl import main\n"
                                 "if __name__ == '__main__':\n"
                                 "    sys.exit(main(sys.argv[1:]))\n") % str(out)
        made = maker.make("git = gitguard_impl:main")
        if not exe.exists():
            built = [m for m in made if m.lower().endswith(".exe")]
            if built:
                shutil.move(built[0], str(exe))
        if not exe.exists():
            return "", ""
        # Git Bash: a `git` script and the BASH_ENV that puts this directory before /mingw64/bin
        (out / "git").write_text('#!/bin/sh\nexec "%s" "$@"\n' % _posix(exe), encoding="utf-8", newline="\n")
        (out / "bash_env.sh").write_text('export PATH="%s:$PATH"\n' % _posix(out), encoding="utf-8", newline="\n")
        for stale in ("git-script.py", "git.py"):
            try:
                (out / stale).unlink()
            except OSError:
                pass
        mark.write_text(stamp, encoding="utf-8")
        return str(out), str(out / "bash_env.sh")
    except Exception:
        return "", ""


if __name__ == "__main__":
    print(ensure())
