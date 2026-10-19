"""The engine CLI the cockpit's NEW verbs spawn (W0–W4 of the steward revision, 2026-09-28): the LIVE engine — the
root the bridge uses (``ECGBERHT_ROOT``, else the ``Ecgberht`` checkout beside this Anchor tree) — never the vendored
bundle under ``vendor/bundled-skills``, which is a distribution snapshot and may lack a flag (the live look of
2026-09-28 caught ``--leave`` ignored by the bundle: two empty instruments on a strip). Falls back to the refinement
client's resolution only when no live engine exists on the host."""
import os
import shutil
from pathlib import Path


def live_cli():
    """Path to the live engine's CLI, or None."""
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    roots = [Path(env)] if env else []
    roots.append(Path(__file__).resolve().parent.parent.parent / "Ecgberht")
    for root in roots:
        cli = root / "bin" / "ecgberht.mjs"
        if cli.is_file():
            return str(cli)
    return None


def resolve():
    """``(node, cli)`` or a failure dict — the live engine first."""
    cli = live_cli()
    if cli:
        node = shutil.which("node")
        return (node, cli) if node else {"ok": False, "error": "dependency-missing", "component": "node"}
    from . import refinement_client as _rc
    return _rc._resolve_dependencies(None, None)
