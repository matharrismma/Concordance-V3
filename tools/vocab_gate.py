"""CI gate: the core must not speak the .org application's vocabulary to users.

Scans string literals (what a user or agent can see) in src/, plus docs/*.md and README.md.
Identifiers and comments are not scanned (WitnessRecord is a class name, not a message).
    PYTHONPATH=src python tools/vocab_gate.py     -> exit 1 on any hit
"""
import ast, glob, re, sys
WORDS = re.compile(r"\b(the keeping|door|doors|house|witness|steward|covenant|the cloud|palace|register of|faces?)\b", re.I)
ALLOW = re.compile(r"\b(register(ed|s)?|registry|registration)\b", re.I)
hits = []
def _docstrings(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            ids.add(id(n.body[0].value))
    return ids


for path in glob.glob("src/concordance/**/*.py", recursive=True):
    if path.endswith("/text.py"):
        continue                                   # the crisis phrase tables ("can't face another day")
    tree = ast.parse(open(path, encoding="utf-8").read())
    docs = _docstrings(tree)                       # docstrings are developer-facing; messages are not
    for n in ast.walk(tree):
        if id(n) in docs:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and WORDS.search(n.value) \
                and not re.fullmatch(r"WITNESS", n.value):   # the v1 gate id, kept for seal-schema stability
            for line in n.value.splitlines():
                if WORDS.search(line):
                    hits.append((path, n.lineno, line.strip()[:110]))
for path in glob.glob("docs/*.md") + ["README.md"]:
    try:
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            if WORDS.search(line):
                hits.append((path, i, line.strip()[:110]))
    except FileNotFoundError:
        pass
for p, l, t in hits:
    print(f"{p}:{l}: {t}")
print(f"{len(hits)} vocabulary hit(s)")
sys.exit(1 if hits else 0)
