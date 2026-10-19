"""C1 Stage 1 codemod: collapse the 3 embedded module-level frontend string
constants (_PROJECT_WINDOW_JS, _PW_SHELL_CSS, _PW_SHELL_TMPL) to read_text()
loads from their byte-identical static mirrors — removing ~5,772 lines from
anchor_gui.py while keeping every emitted byte identical (the embedded render
paths inline the loaded string, which equals the old constant).

Deterministic + idempotent-safe: run once on a clean tree. Verifies byte-
identity before writing. Does NOT touch the generate_html interpolated blob
(that is Stage 2).
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUI = ROOT / "anchor_gui.py"
STATIC = ROOT / "static"

# name -> static asset filename
TARGETS = {
    "_PROJECT_WINDOW_JS": "project-window.js",
    "_PW_SHELL_CSS": "project-window.css",
    "_PW_SHELL_TMPL": "project-window.html",
}


def main():
    src = GUI.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)

    edits = []  # (start_lineno, end_lineno, new_text, name, asset)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        if name not in TARGETS:
            continue
        val = node.value
        if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
            print(f"SKIP {name}: not a plain string constant (already extracted?)")
            continue
        body = val.value
        asset = TARGETS[name]
        static_file = STATIC / asset
        # byte-identity guard: if the mirror exists it MUST match; else create it
        if static_file.exists():
            existing = static_file.read_text(encoding="utf-8")
            if existing != body:
                raise SystemExit(f"ABORT {name}: static/{asset} exists but "
                                 f"differs from the constant (not byte-identical)")
            print(f"OK   {name}: static/{asset} already byte-identical")
        else:
            static_file.write_text(body, encoding="utf-8")
            print(f"MADE {name}: wrote static/{asset} ({len(body)} bytes)")
        new = (f'{name} = (STATIC_DIR / '
               f'{asset_const(name)}).read_text(encoding="utf-8")'
               f'  # C1: extracted verbatim to static/{asset} (byte-identical)\n')
        edits.append((node.lineno, node.end_lineno, new, name, asset))

    # apply edits bottom-up so line numbers stay valid
    for start, end, new, name, asset in sorted(edits, reverse=True):
        lines[start - 1:end] = [new]
        print(f"COLLAPSED {name}: lines {start}-{end} -> 1 line")

    GUI.write_text("".join(lines), encoding="utf-8")
    print("DONE. new anchor_gui.py line count:", len("".join(lines).splitlines()))


def asset_const(name):
    return {
        "_PROJECT_WINDOW_JS": "PROJECT_WINDOW_JS_ASSET",
        "_PW_SHELL_CSS": "PROJECT_WINDOW_CSS_ASSET",
        "_PW_SHELL_TMPL": "PROJECT_WINDOW_SHELL_ASSET",
    }[name]


if __name__ == "__main__":
    main()
