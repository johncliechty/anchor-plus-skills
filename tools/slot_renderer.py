"""C1 include-slot substrate + home-dashboard byte-parity harness (W6a).

The census (W1) forced a C1 amendment: 48 markup-emitting interpolations
(> threshold 40) cannot ride the ``ANCHOR_BOOT`` JSON — they must stay
SERVER-RENDERED. The approved include-layer design (frozen plan, W6a) keeps
each markup fragment in a dedicated ≤50-line helper and reduces the render
function to *data assembly + slot substitution*: the static shell carries
NAMED INCLUDE SLOTS of the form::

    <!--ANCHOR:SLOT:<name>-->

and the server substitutes each placeholder with its helper's output — the
same stdlib idiom as the W5 injection block; no new dependency; the XSS
posture is unchanged (helpers escape exactly as the pre-wave f-string did).

This module is the MECHANISM only (W6a is mechanism-only — ``anchor_gui.py``
is NOT modified here). It ships two pieces:

* :func:`render_slots` — the substitution engine. A slot in the shell with no
  matching helper output, OR a helper output with no matching slot, is a LOUD
  :class:`SlotError` (never a silent drop / silent extra) — the invariant that
  makes W6b's mechanical extraction safe.
* the **byte-parity harness** (:func:`deescape_braces`, :func:`assemble`,
  :func:`byte_parity`, :func:`parity_check`) — extends the W4/W5 byte-parity
  gate to the home dashboard: the OLD f-string emission vs the NEW
  slot-assembled emission, compared byte-for-byte AFTER ``{{``/``}}``
  de-escaping. De-escaping is applied to the STATIC SHELL *before* slot
  substitution (the placeholders carry no braces, so they survive it), so a
  helper output that itself contains ``{{``/``}}`` is never corrupted — the
  faithful reproduction of f-string runtime semantics (a doubled brace in the
  literal is de-escaped once; an interpolated value is inserted verbatim).

Stdlib only (``re``). No product import.
"""

from __future__ import annotations

import re

# A named include slot: ``<!--ANCHOR:SLOT:<name>-->``. NAME is a safe token
# (letters, digits, ``_ . -``) so it round-trips through an HTML comment and a
# JSON artifact untouched. The regex is intentionally strict: a mangled marker
# reads as ordinary text, never as a fuzzy slot match.
SLOT_RE = re.compile(r"<!--ANCHOR:SLOT:([A-Za-z0-9_.\-]+)-->")


class SlotError(RuntimeError):
    """A slot/helper mismatch — raised LOUDLY (never papered over).

    Either the shell declares a slot with no helper output, or a helper output
    was supplied with no matching slot in the shell, or a helper output is not
    a string. Any of these means the assembly is not provably faithful, so the
    substrate refuses rather than shipping a silent divergence.
    """


def slot_names(shell):
    """Return the slot names in ``shell``, in first-appearance order, de-duped.

    A slot name may legitimately appear more than once (the same fragment
    rendered in two places); it is reported once here.
    """
    names = []
    seen = set()
    for m in SLOT_RE.finditer(shell):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def render_slots(shell, helpers):
    """Substitute every ``<!--ANCHOR:SLOT:name-->`` in ``shell`` with
    ``helpers[name]``.

    ``helpers`` maps slot name → the helper's rendered output string. Missing
    and extra entries both raise :class:`SlotError` (the completeness
    invariant); a non-string output raises too. Every occurrence of a repeated
    slot is substituted with the same output. Returns the assembled string.
    """
    shell_slots = {m.group(1) for m in SLOT_RE.finditer(shell)}
    provided = set(helpers)
    missing = shell_slots - provided
    if missing:
        raise SlotError(
            "slot(s) with no helper output (missing): "
            + ", ".join(sorted(missing))
        )
    extra = provided - shell_slots
    if extra:
        raise SlotError(
            "helper output(s) with no matching slot (extra): "
            + ", ".join(sorted(extra))
        )
    for name in shell_slots:
        if not isinstance(helpers[name], str):
            raise SlotError(
                f"helper output for slot {name!r} must be str, got "
                f"{type(helpers[name]).__name__}"
            )
    return SLOT_RE.sub(lambda m: helpers[m.group(1)], shell)


# ── byte-parity harness (home dashboard) ─────────────────────────────────────

def deescape_braces(text):
    """De-escape f-string doubled braces: ``{{`` → ``{`` and ``}}`` → ``}``.

    Applied to the STATIC SHELL (the verbatim f-string literal text) so its
    emitted bytes match the f-string's RUNTIME emission. Non-overlapping
    left-to-right replacement — well-defined for valid f-string literals (every
    literal brace is doubled, so brace runs are even-length).
    """
    return text.replace("{{", "{").replace("}}", "}")


def assemble(shell, helpers, *, deescape=True):
    """Assemble the page the NEW static+slot path emits.

    De-escapes the shell FIRST (so a doubled brace in the literal collapses
    exactly once), THEN substitutes the slots (helper outputs are inserted
    verbatim — never re-de-escaped, matching f-string interpolation). Set
    ``deescape=False`` for a shell that is not an f-string literal (already
    single-braced), e.g. the W4 raw-string case.
    """
    base = deescape_braces(shell) if deescape else shell
    return render_slots(base, helpers)


def byte_parity(reference, candidate):
    """Compare two emissions byte-for-byte (UTF-8). Returns a result dict.

    ``{"identical": True, ...}`` on an EMPTY diff; otherwise ``identical`` is
    False with the first differing byte offset and a small excerpt from each
    side for the gate's failure message.
    """
    ref_b = reference.encode("utf-8")
    cand_b = candidate.encode("utf-8")
    if ref_b == cand_b:
        return {
            "identical": True,
            "reference_len": len(ref_b),
            "candidate_len": len(cand_b),
        }
    limit = min(len(ref_b), len(cand_b))
    off = next((i for i in range(limit) if ref_b[i] != cand_b[i]), limit)
    lo = max(0, off - 30)
    return {
        "identical": False,
        "reference_len": len(ref_b),
        "candidate_len": len(cand_b),
        "first_diff_offset": off,
        "reference_excerpt": ref_b[lo:off + 30].decode("utf-8", "replace"),
        "candidate_excerpt": cand_b[lo:off + 30].decode("utf-8", "replace"),
    }


def parity_check(shell, helpers, reference, *, deescape=True):
    """Assemble ``shell``+``helpers`` and byte-compare to the OLD ``reference``.

    The one-call home-dashboard byte-parity gate: proves the slot-assembled
    emission is byte-identical to the pre-wave f-string emission. Returns the
    :func:`byte_parity` result.
    """
    return byte_parity(reference, assemble(shell, helpers, deescape=deescape))
