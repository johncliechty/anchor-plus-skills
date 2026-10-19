"""Put the containment root on ``sys.path`` for the scoped gate.

The gate runs ``python -m pytest -v tests/ -k "2026_07_29"`` with the working
directory set to ``planning/sleep-2026-07-28/stage2``, so the dated tests must
be able to ``import tools.*`` from that root no matter how pytest resolves its
rootdir (the repository's ``pyproject.toml`` sits three levels up and wins the
rootdir race, which would otherwise leave the build tooling unimportable).

The insert is at position 0 so this effort's ``tools`` package always wins over
any same-named package elsewhere on the path.
"""
import sys
from pathlib import Path

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]

if str(CONTAINMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTAINMENT_ROOT))
