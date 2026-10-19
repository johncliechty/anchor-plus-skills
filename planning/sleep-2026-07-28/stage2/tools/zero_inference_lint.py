"""Zero-inference lint — W6, Phase 2.

Flags any code path that derives a **user-facing label** from a numeric value
being zero (the defect class: ``if cost == 0: return "(subscription)"``).

Cost labels must come from ``cost_state`` (W7). Measured zeros are
``NamedState.zero_measured`` via ``render_state`` (W6). Inferring a display
string solely because a number is 0 is a wave-gate failure.

Usage::

    from tools.zero_inference_lint import lint_source, lint_paths, scan

    violations = lint_source(src, path="example.py")
    # each violation has .path, .line, .message

CLI (orchestrator / wave gate)::

    python -m tools.zero_inference_lint path/to/file.py [more paths...]

Exit code 1 when any violation is found.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

# --------------------------------------------------------------------------
# Public result type
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ZeroInferenceViolation:
    """One zero-derived user-facing label site."""

    path: str
    line: int
    message: str
    snippet: str = ""

    def __str__(self) -> str:
        loc = "%s:%d" % (self.path, self.line)
        if self.snippet:
            return "%s: %s — %s" % (loc, self.message, self.snippet)
        return "%s: %s" % (loc, self.message)


# --------------------------------------------------------------------------
# Heuristics
# --------------------------------------------------------------------------

#: Names that commonly carry measured quantities on honesty surfaces.
_NUMERIC_NAME_HINTS = re.compile(
    r"(cost|total|amount|price|dollars?|cents?|usage|count|sum|value|"
    r"balance|fee|spend|spent|tokens?|minutes?|hours?|qty|quantity|"
    r"rollup|metric|num|n_)",
    re.IGNORECASE,
)

#: User-facing label shapes that must not be chosen solely because n == 0.
_LABEL_HINTS = re.compile(
    r"subscription|unmeasured|unknown|empty|pending|n/?a|none|"
    r"free|included|covered|zero|—|–",
    re.IGNORECASE,
)

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".mypy_cache",
        ".tox",
    }
)


def _is_zero_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == 0 or node.value == 0.0
    # Py<3.8 legacy (still tolerate if present)
    if isinstance(node, ast.Num):  # type: ignore[attr-defined]
        return node.n == 0 or node.n == 0.0  # type: ignore[attr-defined]
    return False


def _name_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _name_of(node.value)
    return ""


def _compare_is_zero_test(test: ast.AST) -> Optional[str]:
    """If ``test`` is a comparison against 0, return the other side's name."""
    if not isinstance(test, ast.Compare):
        # ``not cost`` is not a zero-inference pattern we claim here.
        return None
    # Only simple single-op compares: ``x == 0`` / ``0 == x`` / ``x != 0``
    # We flag equality-to-zero used to pick labels; inequality is less common
    # for the banned pattern but still suspicious with a label in the body.
    if len(test.ops) != 1 or len(test.comparators) != 1:
        return None
    op = test.ops[0]
    if not isinstance(op, (ast.Eq, ast.Is, ast.NotEq, ast.IsNot)):
        # Also catch ``cost > 0`` inverted label branches less specifically —
        # the GWT is specifically cost == 0 → label. Stick to Eq/Is.
        if not isinstance(op, (ast.Eq, ast.Is)):
            return None
    left, right = test.left, test.comparators[0]
    if _is_zero_constant(right):
        return _name_of(left) or "<expr>"
    if _is_zero_constant(left):
        return _name_of(right) or "<expr>"
    return None


def _string_value(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # f-string — take static parts only
        parts: List[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
        return "".join(parts) if parts else None
    return None


def _body_emits_label(body: Sequence[ast.stmt]) -> Optional[str]:
    """Return a sample label string if the body returns/assigns a UI string."""
    for stmt in body:
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            s = _string_value(stmt.value)
            if s is not None and _looks_like_label(s):
                return s
            # return some_fn("label") — check call args
            if isinstance(stmt.value, ast.Call):
                for arg in list(stmt.value.args) + [
                    k.value for k in stmt.value.keywords
                ]:
                    s = _string_value(arg)
                    if s is not None and _looks_like_label(s):
                        return s
        if isinstance(stmt, ast.Assign):
            s = _string_value(stmt.value)
            if s is not None and _looks_like_label(s):
                # Prefer assignments to label-ish names, but any is enough.
                return s
        if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            s = _string_value(stmt.value)
            if s is not None and _looks_like_label(s):
                return s
        if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With)):
            nested = _body_emits_label(stmt.body)
            if nested:
                return nested
            nested = _body_emits_label(getattr(stmt, "orelse", []) or [])
            if nested:
                return nested
    return None


def _looks_like_label(s: str) -> bool:
    text = s.strip()
    if not text:
        return False
    # Parenthesized display tokens like "(subscription)" are always labels.
    if text.startswith("(") and text.endswith(")"):
        return True
    # Dollar / free-text display
    if text.startswith("$"):
        return True
    if _LABEL_HINTS.search(text):
        return True
    # Short non-numeric UI tokens
    if len(text) <= 40 and not re.fullmatch(r"[-+]?\d+(\.\d+)?", text):
        # Avoid flagging pure log format strings with many braces
        if text.count("%") >= 2 or text.count("{") >= 2:
            return False
        # Require at least one letter — UI labels are words
        if re.search(r"[A-Za-z]", text):
            return True
    return False


def _numeric_name_relevant(name: str) -> bool:
    if not name or name == "<expr>":
        # Unknown expr compared to 0 — still flag if body emits a label
        # (conservative: only when name is empty-ish we still report).
        return True
    return bool(_NUMERIC_NAME_HINTS.search(name))


class _ZeroInferenceVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.violations: List[ZeroInferenceViolation] = []

    def visit_If(self, node: ast.If) -> None:
        self._check_branch(node.test, node.body)
        # elif chain lives in orelse as nested If
        for stmt in node.orelse:
            if isinstance(stmt, ast.If):
                self._check_branch(stmt.test, stmt.body)
        self.generic_visit(node)

    def _check_branch(self, test: ast.AST, body: Sequence[ast.stmt]) -> None:
        name = _compare_is_zero_test(test)
        if name is None:
            return
        if not _numeric_name_relevant(name):
            # Still flag if the body clearly emits a subscription-style label
            # even when the name is generic (GWT uses ``cost``).
            label = _body_emits_label(body)
            if label and _LABEL_HINTS.search(label):
                self._report(test, name, label)
            return
        label = _body_emits_label(body)
        if label is not None:
            self._report(test, name, label)

    def _report(self, test: ast.AST, name: str, label: str) -> None:
        line = getattr(test, "lineno", 1) or 1
        msg = (
            "zero-inference violation: user-facing label derived from "
            "%s == 0 (use cost_state / NamedState, never infer from zero)"
            % name
        )
        self.violations.append(
            ZeroInferenceViolation(
                path=self.path,
                line=line,
                message=msg,
                snippet=repr(label),
            )
        )


def lint_source(
    source: str,
    path: str = "<string>",
) -> List[ZeroInferenceViolation]:
    """Lint a Python source string; return zero-inference violations."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [
            ZeroInferenceViolation(
                path=path,
                line=exc.lineno or 1,
                message="zero-inference lint: syntax error — %s" % exc.msg,
            )
        ]
    visitor = _ZeroInferenceVisitor(path=path)
    visitor.visit(tree)

    # Regex safety net for the exact GWT pattern even if AST edge cases miss.
    for match in re.finditer(
        r"(?m)^(?P<indent>\s*)if\s+(?P<name>\w+)\s*==\s*0\s*:\s*\n"
        r"(?P=indent)\s+return\s+(?P<q>['\"])(?P<label>\([^'\"]*\)|[^'\"]+)(?P=q)",
        source,
    ):
        name = match.group("name")
        label = match.group("label")
        if not _numeric_name_relevant(name) and not _LABEL_HINTS.search(label):
            continue
        line = source.count("\n", 0, match.start()) + 1
        already = any(v.line == line and v.path == path for v in visitor.violations)
        if not already:
            visitor.violations.append(
                ZeroInferenceViolation(
                    path=path,
                    line=line,
                    message=(
                        "zero-inference violation: user-facing label derived "
                        "from %s == 0 (use cost_state / NamedState, never "
                        "infer from zero)" % name
                    ),
                    snippet=repr(label),
                )
            )
    return visitor.violations


def lint_path(path: Union[str, Path]) -> List[ZeroInferenceViolation]:
    """Lint one file path."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            ZeroInferenceViolation(
                path=str(p),
                line=1,
                message="zero-inference lint: cannot read file — %s" % exc,
            )
        ]
    # Report with a relative-looking path when possible (no host-absolute requirement).
    display = str(p).replace("\\", "/")
    return lint_source(text, path=display)


def lint_paths(paths: Iterable[Union[str, Path]]) -> List[ZeroInferenceViolation]:
    """Lint many files; concatenate violations."""
    out: List[ZeroInferenceViolation] = []
    for path in paths:
        out.extend(lint_path(path))
    return out


def scan(
    root: Union[str, Path],
    *,
    suffixes: Sequence[str] = (".py",),
) -> List[ZeroInferenceViolation]:
    """Walk ``root`` and lint every matching source file."""
    root_p = Path(root)
    files: List[Path] = []
    if root_p.is_file():
        files = [root_p]
    else:
        for dirpath, dirnames, filenames in os.walk(str(root_p)):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            for fn in filenames:
                if any(fn.endswith(sfx) for sfx in suffixes):
                    files.append(Path(dirpath) / fn)
    return lint_paths(files)


def format_report(violations: Sequence[ZeroInferenceViolation]) -> str:
    if not violations:
        return "zero-inference lint: clean (0 violations)\n"
    lines = ["zero-inference lint: %d violation(s)" % len(violations)]
    for v in violations:
        lines.append("  %s" % v)
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "usage: python -m tools.zero_inference_lint <path> [path...]",
            file=sys.stderr,
        )
        return 2
    violations = lint_paths(args)
    sys.stdout.write(format_report(violations))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
