"""Mutation check: a green benchmark must be load-bearing.

    PYTHONPATH=src python tools/mutate.py --sample 20 [--seed 1]

Picks N verifier modules at random, flips ONE arithmetic operator (or comparison) in each, re-runs the
benchmark in a subprocess, and reports whether the mutation was DETECTED (any FP or FN, or an exception).
Restores every file. Exit 1 if any mutation went undetected.
"""
import glob, os, random, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "concordance", "verifiers")
FLIPS = [(r"(?<=[\w\)\]])\s\*\s(?=[\w\(])", " / "), (r"(?<=[\w\)\]])\s\+\s(?=[\w\(])", " - "),
         (r"(?<=[\w\)\]])\s-\s(?=[\w\(])", " + "), (r"\*\*\s*2\b", "** 3"), (r"<=", ">="), (r"\babs\(", "float(")]


OP_FLIPS = {"*": "/", "+": "-", "-": "+", "<=": ">=", ">=": "<=", "<": ">=", ">": "<="}


def mutate_once(path: str, rnd: random.Random):
    """Flip ONE operator token in executable code — never inside a string, comment or docstring."""
    import io, tokenize
    src = open(path, encoding="utf-8").read()
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    cands = [t for t in toks if t.type == tokenize.OP and t.string in OP_FLIPS]
    # skip unary minus (previous significant token is an operator or an open paren)
    good = []
    for k, t in enumerate(cands):
        idx = toks.index(t)
        prev = toks[idx - 1]
        if t.string in ("+", "-") and (prev.type == tokenize.OP and prev.string in "([,=:+-*/<>%") :
            continue
        good.append(t)
    if not good:
        return None, None
    t = rnd.choice(good)
    lines = src.splitlines(keepends=True)
    (r0, c0), (r1, c1) = t.start, t.end
    line = lines[r0 - 1]
    lines[r0 - 1] = line[:c0] + OP_FLIPS[t.string] + line[c1:]
    return "".join(lines), f"line {r0}: {t.string!r} -> {OP_FLIPS[t.string]!r}"


def run_domain_tests(mod: str) -> bool:
    """The per-domain tests are half of the gate (tools/check.py runs benchmark + suite). Detected if red."""
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    tests = [t for t in glob.glob(os.path.join(ROOT, "tests", f"test_{mod}*.py"))]
    if not tests:
        return False
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *tests],
                       capture_output=True, text=True, env=env, timeout=600)
    return r.returncode != 0


def run_benchmark() -> bool:
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "benchmark.py"), "--json"],
                       capture_output=True, text=True, env=env, timeout=600)
    if r.returncode != 0:
        return True                                        # a FP (exit 1) or a crash counts as detected
    import json
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return True
    return bool(d["totals"]["false_positives"] or d["totals"]["false_negatives"])


def main():
    n = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else 10
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1
    rnd = random.Random(seed)
    files = sorted(f for f in glob.glob(os.path.join(SRC, "*.py"))
                   if not os.path.basename(f).startswith(("_", "base", "spec", "riemann", "retrieval")))
    picked = rnd.sample(files, min(n, len(files)))
    detected = 0
    for f in picked:
        original = open(f, encoding="utf-8").read()
        mutated, what = mutate_once(f, rnd)
        if mutated is None:
            print(f"skip   {os.path.basename(f)}: nothing to flip"); continue
        try:
            open(f, "w", encoding="utf-8").write(mutated)
            by_bench = run_benchmark()
            by_tests = (not by_bench) and run_domain_tests(os.path.basename(f)[:-3])
            ok = by_bench or by_tests
            what += "  [benchmark]" if by_bench else ("  [domain tests]" if by_tests else "")
        finally:
            open(f, "w", encoding="utf-8").write(original)
        detected += ok
        print(f"{'DETECT' if ok else 'MISSED'} {os.path.basename(f)}: {what}")
    print(f"{detected}/{len(picked)} mutations detected")
    sys.exit(0 if detected == len(picked) else 1)


if __name__ == "__main__":
    main()
