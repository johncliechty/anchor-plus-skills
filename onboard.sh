#!/usr/bin/env bash
# Cold-start launcher for macOS and Linux collaborators.
# Verifies Python >= 3.8 and delegates to `python3 -m share_onboard "$@"`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY_BIN=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
            PY_BIN="$cand"
            break
        fi
    fi
done

if [ -z "$PY_BIN" ]; then
    echo "Anchor onboarding requires Python 3.8 or newer." >&2
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "Install Python on macOS via Homebrew ('brew install python') or https://www.python.org/downloads/ and re-run ./onboard.sh" >&2
    else
        echo "Install Python 3 via your package manager (e.g. 'sudo apt install python3') and re-run ./onboard.sh" >&2
    fi
    exit 1
fi

exec "$PY_BIN" -m share_onboard "$@"
