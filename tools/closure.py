"""Import closure of the concordance package from a set of entry modules.

    PYTHONPATH=src python tools/closure.py derivation audit receipts [--lazy] [--src src/concordance]

Walks `from . import x`, `from .x import y`, `from .pkg.x import y`, `import concordance.x` in each module
(module-level only by default; --lazy also follows imports inside functions). Prints the sorted closure
with one line per module: name, lines, and which module first pulled it in. Exit code 0.
"""
from __future__ import annotations
import ast, os, sys
from collections import deque


def _mods(src):
    out = {}
    for root, _, files in os.walk(src):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, src)[:-3].replace(os.sep, ".")
                if rel.endswith(".__init__"):
                    rel = rel[:-9]
                out[rel] = p
    return out


def _imports(path, lazy):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = []
    nodes = ast.walk(tree) if lazy else [n for n in tree.body] + [
        m for n in tree.body if isinstance(n, (ast.If, ast.Try)) for m in ast.walk(n)]
    for n in nodes:
        if isinstance(n, ast.ImportFrom):
            if n.level and n.level > 0:
                base = n.module or ""
                for a in n.names:
                    found.append((n.level, base, a.name))
            elif n.module and n.module.startswith("concordance"):
                for a in n.names:
                    found.append((0, n.module, a.name))
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("concordance"):
                    found.append((0, a.name, None))
    return found


def _resolve(cur, level, base, name, mods):
    if level == 0:
        parts = base.split(".")[1:]  # strip 'concordance'
        cand = ".".join(parts + ([name] if name else []))
        for c in (cand, ".".join(parts)):
            if c in mods:
                return c
        return None
    pkg = cur.split(".")[:-1] if cur in mods and not mods[cur].endswith("__init__.py") else cur.split(".")
    pkg = pkg[: len(pkg) - (level - 1)]
    for c in (".".join(pkg + ([base] if base else []) + [name]),
              ".".join(pkg + ([base] if base else []))):
        c = c.strip(".")
        if c in mods:
            return c
    return None


def closure(entries, src, lazy=False):
    mods = _mods(src)
    seen, why = {}, {}
    q = deque(entries)
    for e in entries:
        why[e] = "<entry>"
    while q:
        cur = q.popleft()
        if cur in seen or cur not in mods:
            continue
        seen[cur] = sum(1 for _ in open(mods[cur], encoding="utf-8"))
        for level, base, name in _imports(mods[cur], lazy):
            tgt = _resolve(cur, level, base, name, mods)
            if tgt and tgt not in seen and tgt not in why:
                why[tgt] = cur
                q.append(tgt)
    return seen, why


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lazy = "--lazy" in sys.argv
    src = "src/concordance"
    for i, a in enumerate(sys.argv):
        if a == "--src":
            src = sys.argv[i + 1]
            args = [x for x in args if x != src]
    seen, why = closure(args, src, lazy)
    total = 0
    for m in sorted(seen):
        total += seen[m]
        print(f"{m:48s} {seen[m]:6d}  <- {why[m]}")
    print(f"# {len(seen)} modules, {total} lines ({'lazy' if lazy else 'module-level'} imports)")
