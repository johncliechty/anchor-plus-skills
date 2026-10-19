"""Skill Foundry v2 — the HOST-ENFORCED journaling write-back seam (Wave 2).

The documented v1 failure mode is honor-system capture starving the sleep
loop: journal entries were hand-written (or not written at all), so the corpus
never filled itself.  This module is the fix — capture as a BY-PRODUCT at the
one seam every host-mediated run already passes through.  Anchor's gandalf
adapter calls :func:`journal_run_writeback` from its finalize path with the
facts it already holds (inputs / verdict / timing / outcome); Wave 3 moves the
same call into the generic manifest-driven skill_runner.

Shape (per ``foundry_decisions`` DR-04, ``PROCESS_TELEMETRY_DEPTH =
OUTCOME_PLUS_RECOVERY``):

* **Skeleton** — a 7-field entry (``JOURNAL_ENTRY_FIELDS``: provenance ·
  operation_kind · model_cost · inputs_ref · outputs_ref · verdict_timing ·
  outcome_linkage) appended to ``<skill_dir>/journal/<entry_id>.md`` as
  frontmatter markdown, capped at ``SIDE_CHANNEL_DESIGN['skeleton_max_bytes']``
  (2 KB) — bulk is referenced, never inlined.
* **Droppable side-channel** — the heavy payloads (raw drafts, graded output,
  full inputs) land in ``<skill_dir>/journal/side/<run_id>/`` and are pointed
  at by the skeleton's ``inputs_ref`` / ``outputs_ref``.  Deleting the side
  channel NEVER breaks a skeleton entry (the Wave-5 kernel parser reads
  skeleton entries only).

THE DRIFT INVARIANT (grep-gated by ``tests/test_foundry_journal_w2.py``):
this module is the ONLY product code that writes under a ``journal/`` dir.
A second writer is an honor-system capture path and fails the gate.

Also here: :func:`backfill_plan_section7` — parse a PLAN.md ``## 7`` review
log (append-only status ledger) into schema-valid skeleton entries, so the
system-level history feeds the Wave-5 kernel like any other journal.

Stdlib only (Anchor's no-dep rule); imports nothing but ``foundry_decisions``.
"""

import json
import os
import re
import time
from pathlib import Path

import foundry_decisions as _fd


# ── Constants (single source: the Wave-1 decision module) ────────────────────

#: Bump when a fix changes what a correct skeleton entry looks like.
ENTRY_SCHEMA_VERSION = 1

#: The journal dir under a skill dir, and the side-channel dir under it.
JOURNAL_DIRNAME = "journal"
SIDE_DIRNAME = "side"

#: The 7 skeleton fields (DR-04). The seam validates against this tuple, so a
#: decision-module drift breaks journaling loudly instead of silently forking.
ENTRY_FIELDS = tuple(_fd.JOURNAL_ENTRY_FIELDS)

#: The always-on skeleton stays this small; bulk goes to the side channel.
SKELETON_MAX_BYTES = int(_fd.SIDE_CHANNEL_DESIGN["skeleton_max_bytes"])

#: Honest ref placeholder when the side channel could not be written (disk
#: error). The skeleton entry still lands — droppable means optional.
SIDE_UNAVAILABLE = "(side-channel-unavailable)"

#: Frontmatter meta keys carried alongside the 7 fields.
_META_KEYS = ("id", "entry_schema", "ts")

#: Clip caps that keep the skeleton under the byte budget by construction.
_MAX_VERDICT_CHARS = 240
_MAX_REF_CHARS = 300
_MAX_FIELD_CHARS = 600


# ── Paths ─────────────────────────────────────────────────────────────────────

def journal_dir(skill_dir) -> Path:
    """``<skill_dir>/journal/`` — where skeleton entries live."""
    return Path(skill_dir) / JOURNAL_DIRNAME


def side_dir(skill_dir, run_id) -> Path:
    """``<skill_dir>/journal/side/<run_id>/`` — the droppable side channel."""
    return journal_dir(skill_dir) / SIDE_DIRNAME / str(run_id)


# ── Side channel (heavy I/O) ─────────────────────────────────────────────────

def write_side_artifact(skill_dir, run_id, name, payload):
    """Write one heavy artifact into the side channel → its REL ref (or None).

    ``payload`` may be a str (written verbatim) or any JSON-able object.  The
    returned ref (``journal/side/<run_id>/<name>``, POSIX, relative to the
    skill dir) is what the skeleton's ``inputs_ref``/``outputs_ref`` carry.
    Best-effort: an OS failure returns ``None`` — the side channel is
    droppable, so its absence never blocks the skeleton. Never raises.
    """
    try:
        d = side_dir(skill_dir, run_id)
        d.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, indent=2, ensure_ascii=False,
                              default=str)
        (d / str(name)).write_text(text, encoding="utf-8")
        return "/".join((JOURNAL_DIRNAME, SIDE_DIRNAME, str(run_id),
                         str(name)))
    except Exception:
        return None


# ── Skeleton entry: render / parse / validate ────────────────────────────────

def _clip(value, cap):
    s = str(value if value is not None else "")
    s = " ".join(s.split())  # single-line, collapsed whitespace
    return s if len(s) <= cap else s[:cap - 1] + "…"


def _render_value(value):
    """One single-line frontmatter value: strings verbatim, else compact JSON."""
    if isinstance(value, str):
        return _clip(value, _MAX_FIELD_CHARS)
    try:
        return _clip(json.dumps(value, ensure_ascii=False, default=str,
                                separators=(",", ":")), _MAX_FIELD_CHARS)
    except Exception:
        return _clip(str(value), _MAX_FIELD_CHARS)


def render_entry(entry: dict) -> str:
    """Render a skeleton entry as frontmatter markdown (the on-disk form)."""
    lines = ["---"]
    for key in _META_KEYS:
        if key in entry:
            lines.append("%s: %s" % (key, _render_value(entry[key])))
    for key in ENTRY_FIELDS:
        lines.append("%s: %s" % (key, _render_value(entry.get(key))))
    lines.append("---")
    lines.append("")
    lines.append("Host-emitted skeleton entry (foundry-v2 Wave 2; capture is "
                 "a by-product, never author action). Heavy detail, if any, "
                 "lives in the droppable side channel referenced above.")
    lines.append("")
    return "\n".join(lines)


def parse_entry(text: str):
    """Parse a rendered entry back into a dict (values re-JSON'd best-effort).

    Returns ``{}`` when the text carries no frontmatter block. The Wave-5
    kernel parser builds on this exact shape — skeleton only, side channel
    never required.
    """
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", text, re.DOTALL)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        try:
            out[key] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            out[key] = raw
    return out


def validate_entry(entry: dict, rendered: str = None) -> list:
    """Return a list of schema problems (empty = a valid skeleton entry).

    Checks: all 7 DR-04 fields present + non-empty; ``operation_kind`` on the
    DR-01 op-kind enum; refs are short single-line references (never inline
    bulk); the rendered form fits the skeleton byte budget.
    """
    problems = []
    for field in ENTRY_FIELDS:
        v = entry.get(field)
        if v is None or (isinstance(v, (str, dict, list, tuple)) and not v):
            problems.append("missing/empty field: %s" % field)
    kind = entry.get("operation_kind")
    if kind and kind not in _fd.OP_KINDS:
        problems.append("operation_kind %r not in OP_KINDS %r"
                        % (kind, _fd.OP_KINDS))
    for ref_field in ("inputs_ref", "outputs_ref"):
        ref = entry.get(ref_field)
        if isinstance(ref, str) and ref:
            if "\n" in ref or len(ref) > _MAX_REF_CHARS:
                problems.append("%s is inline bulk, not a reference"
                                % ref_field)
    if rendered is None:
        rendered = render_entry(entry)
    size = len(rendered.encode("utf-8"))
    if size > SKELETON_MAX_BYTES:
        problems.append("skeleton is %d bytes > %d cap"
                        % (size, SKELETON_MAX_BYTES))
    return problems


def append_entry(skill_dir, entry_id, entry: dict) -> Path:
    """Append ONE skeleton entry to ``<skill_dir>/journal/<entry_id>.md``.

    THE low-level journal writer — the drift gate proves no other product
    code writes under a journal dir. Validates against the DR-04 schema and
    raises ``ValueError`` on a malformed entry (a loud seam beats a silently
    forked schema). Atomic: tmp-write + replace.
    """
    full = dict(entry)
    full.setdefault("id", str(entry_id))
    full.setdefault("entry_schema", ENTRY_SCHEMA_VERSION)
    full.setdefault("ts", round(time.time(), 3))
    rendered = render_entry(full)
    problems = validate_entry(full, rendered)
    if problems:
        raise ValueError("invalid journal entry %s: %s"
                         % (entry_id, "; ".join(problems)))
    d = journal_dir(skill_dir)
    d.mkdir(parents=True, exist_ok=True)
    target = d / (str(entry_id) + ".md")
    tmp = d / (str(entry_id) + ".md.tmp")
    tmp.write_text(rendered, encoding="utf-8")
    os.replace(str(tmp), str(target))
    return target


# ── The write-back seam (what a host adapter calls at finalize) ──────────────

def journal_run_writeback(skill_dir, *, run_id, operation_kind, provenance,
                          model_cost, inputs, outputs, verdict, timing,
                          outcome, linkage):
    """Auto-append the 7-field skeleton for one finished host-mediated run.

    The caller (gandalf's finalize path now; the generic runner from Wave 3)
    passes the facts it already holds — nothing is asked of the skill author
    (zero author action). Heavy payloads (``inputs``/``outputs``) are shunted
    to the droppable side channel; the skeleton carries only refs.

    Returns the written entry ``Path``, or ``None`` on failure — journaling
    must NEVER crash or block the run it records.
    """
    try:
        inputs_ref = write_side_artifact(
            skill_dir, run_id, "inputs.json", inputs) or SIDE_UNAVAILABLE
        outputs_ref = write_side_artifact(
            skill_dir, run_id, "outputs.json", outputs) or SIDE_UNAVAILABLE
        verdict_timing = {"verdict": _clip(verdict, _MAX_VERDICT_CHARS)}
        if isinstance(timing, dict):
            verdict_timing.update(timing)
        outcome_linkage = {"outcome": str(outcome or "unknown")}
        if isinstance(linkage, dict):
            outcome_linkage.update(linkage)
        entry = {
            "provenance": str(provenance or ""),
            "operation_kind": str(operation_kind or ""),
            "model_cost": model_cost if model_cost else {"model": "unrecorded"},
            "inputs_ref": inputs_ref,
            "outputs_ref": outputs_ref,
            "verdict_timing": verdict_timing,
            "outcome_linkage": outcome_linkage,
        }
        return append_entry(skill_dir, run_id, entry)
    except Exception:
        return None


# ── PLAN.md §7 backfill (the system-level journal) ───────────────────────────

_PLAN7_HEADER = re.compile(r"^##\s*7\.", re.MULTILINE)
_ANY_HEADER = re.compile(r"^##\s*\d", re.MULTILINE)
_BULLET_DATE = re.compile(r"`(\d{4}-\d{2}-\d{2})`")
_BULLET_ACTOR = re.compile(r"\*\*(.+?)\*\*")


def _plan7_bullets(plan_text: str) -> list:
    """The top-level ``- `` bullets of the ``## 7`` section, in order."""
    m = _PLAN7_HEADER.search(plan_text)
    if not m:
        return []
    tail = plan_text[m.end():]
    nxt = _ANY_HEADER.search(tail)
    section = tail[:nxt.start()] if nxt else tail
    bullets = []
    for line in section.splitlines():
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif bullets and line.strip() and not line.startswith(("#", "-")):
            # continuation / indented sub-line folds into the open bullet
            bullets[-1] += " " + line.strip()
    return [b for b in bullets if b]


def backfill_plan_section7(plan_md_path, journal_dir_path) -> list:
    """Backfill a PLAN.md ``## 7`` review log as a system-level journal.

    One schema-valid 7-field skeleton entry per top-level review-log bullet,
    written to ``journal_dir_path`` as ``plan7-NNNN.md`` (idempotent: same
    input → same files). Returns the written Paths. The v1 review log was
    exactly the honor-system system journal; this puts it on the Wave-5
    kernel's consumption path in the host-enforced shape.
    """
    plan = Path(plan_md_path)
    text = plan.read_text(encoding="utf-8", errors="replace")
    out_dir = Path(journal_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, bullet in enumerate(_plan7_bullets(text), start=1):
        date_m = _BULLET_DATE.search(bullet)
        actor_m = _BULLET_ACTOR.search(bullet)
        date = date_m.group(1) if date_m else "unknown-date"
        actor = actor_m.group(1) if actor_m else "unknown-actor"
        summary = re.sub(r"[*`]", "", bullet)
        entry_id = "plan7-%04d" % i
        entry = {
            "id": entry_id,
            "provenance": "backfill:PLAN.md#7:%s" % _clip(actor, 80),
            "operation_kind": "run",
            "model_cost": {"model": "unrecorded", "billed_cost_usd": 0.0,
                           "cache_tokens": 0},
            "inputs_ref": "PLAN.md#7",
            "outputs_ref": "PLAN.md#7:entry-%d" % i,
            "verdict_timing": {"verdict": _clip(summary, _MAX_VERDICT_CHARS),
                               "date": date},
            "outcome_linkage": {"outcome": "recorded",
                                "source": "PLAN.md#7", "entry": i},
        }
        rendered = render_entry(entry)
        problems = validate_entry(entry, rendered)
        if problems:
            raise ValueError("plan7 backfill entry %d invalid: %s"
                             % (i, "; ".join(problems)))
        target = out_dir / (entry_id + ".md")
        tmp = out_dir / (entry_id + ".md.tmp")
        tmp.write_text(rendered, encoding="utf-8")
        os.replace(str(tmp), str(target))
        written.append(target)
    return written


if __name__ == "__main__":  # pragma: no cover — tiny operator convenience
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == "backfill":
        paths = backfill_plan_section7(sys.argv[2], sys.argv[3])
        print("backfilled %d entries -> %s" % (len(paths), sys.argv[3]))
    else:
        print("usage: python foundry_journal.py backfill <PLAN.md> "
              "<journal_dir>")
