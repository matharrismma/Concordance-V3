"""Which verify_* functions no benchmark case executes. The honest coverage number for the verifier set.

    PYTHONPATH=src python tools/unreached.py        # prints the list; exit 1 if any are not in the ALLOWED set
"""
import ast, json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Reasons a function may stay unreached, stated: policy (no code execution), data-bound (needs the .org
# corpus / Strong's / WordNet / the combat grammar), or over the wall-clock budget. Anything else is a gap.
ALLOWED = {
    "computer_science.static_termination": "policy: executes caller code",
    "computer_science.functional_correctness": "policy: executes caller code",
    "computer_science.runtime_complexity": "policy: executes caller code",
    "computer_science.space_complexity": "policy: executes caller code",
    "computer_science.determinism": "policy: executes caller code",
    "elliptic_curves.bsd_formula": "over budget: L-value computation exceeds the 8 s verify window",
    "number_theory.li_criterion": "over budget: Li coefficients exceed the 8 s verify window",
    "linguistics.strongs_resolution": "data-bound: Strong's lexicon lives with the .org app",
    "linguistics.word_count": "data-bound: Strong's", "linguistics.transliteration": "data-bound: Strong's",
    "linguistics.gloss": "data-bound: Strong's", "linguistics.cognate": "data-bound: Strong's",
    "linguistics.semantic_relation": "data-bound: WordNet thesaurus.db lives with the .org app",
    "retrieval.recall_of_known": "data-bound: needs a corpus", "retrieval.rank_of_target": "data-bound: needs a corpus",
    "retrieval.no_false_silence": "data-bound: needs a corpus",
    "wordcraft.morphology": "data-bound: pronunciation/etymology shelves live with the .org app",
    "pressure_fighting.card": "data-bound: the combat grammar's card tables",
    "governance.domain_profile": "called by the engine's gate path, not by a verifier packet",
}
env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
subprocess.run([sys.executable, "-m", "coverage", "run", "--include=src/concordance/verifiers/*",
                "tools/benchmark.py", "--json"], cwd=ROOT, env=env, capture_output=True)
subprocess.run([sys.executable, "-m", "coverage", "json", "-o", ".coverage.json", "-q"], cwd=ROOT, env=env, capture_output=True)
cov = json.load(open(os.path.join(ROOT, ".coverage.json")))["files"]
missing, total = [], 0
for path, d in cov.items():
    if "/verifiers/" not in path or os.path.basename(path).startswith(("_", "base", "spec")):
        continue
    executed = set(d["executed_lines"]); mod = os.path.basename(path)[:-3]
    for n in ast.parse(open(os.path.join(ROOT, path) if not os.path.isabs(path) else path).read()).body:
        if isinstance(n, ast.FunctionDef) and n.name.startswith("verify_"):
            total += 1
            if not (set(range(n.body[0].lineno, n.end_lineno + 1)) & executed):
                missing.append(f"{mod}.{n.name[7:]}")
gaps = [m for m in missing if m not in ALLOWED]
print(f"{total} verify_* functions; {total - len(missing)} reached by the benchmark; {len(missing)} unreached "
      f"({len(missing) - len(gaps)} with a stated reason, {len(gaps)} gaps)")
for m in missing:
    print(f"  {m:45s} {ALLOWED.get(m, '<-- GAP: write a golden or delete the check')}")
sys.exit(1 if gaps else 0)
