"""Harvest per-CHECK goldens from the test suite.

Runs pytest with a hook on verifiers.run_for_domain that records every (domain, packet, result) that passed
through a verifier. For each check name, keeps the first CONFIRMED packet as the TRUE golden and derives a
FALSE golden by perturbing the claimed numeric field (×1.37, or flipping a claimed boolean); the false
golden is kept only if the engine actually rejects it (so a perturbation that lands inside a tolerance is
dropped, never labelled). Writes data/check_goldens.jsonl — benchmark tier 4.

    PYTHONPATH=src python tools/harvest_goldens.py
"""
import copy, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(tempfile.gettempdir(), "concordance_harvest.jsonl")
HOOK = f'''
import json, atexit
from concordance import verifiers as V
_orig = V.run_for_domain
_seen = set()
_f = open({REC!r}, "a")
def _rec(domain, packet, surface="secular"):
    res = _orig(domain, packet, surface)
    try:
        for r in res:
            key = (r.name, r.status)
            if r.status == "CONFIRMED" and key not in _seen:
                _seen.add(key)
                _f.write(json.dumps({{"domain": domain, "check": r.name, "packet": packet}}, default=str) + "\\n")
    except Exception:
        pass
    return res
V.run_for_domain = _rec
import concordance.derivation as D
D._verifiers.run_for_domain = _rec
'''


def harvest():
    if os.path.exists(REC):
        os.remove(REC)
    conf = os.path.join(ROOT, "tests", "conftest.py")
    original = open(conf, encoding="utf-8").read()
    try:
        open(conf, "w", encoding="utf-8").write(original + "\n# --- harvest hook (temporary) ---\n" + HOOK)
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
    finally:
        open(conf, "w", encoding="utf-8").write(original)
    rows = [json.loads(l) for l in open(REC, encoding="utf-8")] if os.path.exists(REC) else []
    return rows


def _perturb(packet):
    """Return (perturbed_packet, how) or (None, None)."""
    p = copy.deepcopy(packet)

    def walk(o, path=""):
        if isinstance(o, dict):
            for k in list(o):
                v = o[k]
                if k.startswith("claimed") or k.startswith("expected"):
                    if isinstance(v, bool):
                        o[k] = not v; return f"{path}{k}: flipped"
                    if isinstance(v, (int, float)) and v != 0:
                        o[k] = v * 1.37 if isinstance(v, float) else int(v * 1.37) + 1; return f"{path}{k}: ×1.37"
                    if isinstance(v, (int, float)) and v == 0:
                        o[k] = 1; return f"{path}{k}: 0→1"
                    if isinstance(v, str) and v.replace(".", "", 1).lstrip("-").isdigit():
                        o[k] = str(float(v) * 1.37); return f"{path}{k}: ×1.37"
                    if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
                        o[k] = [x * 1.37 + 1 for x in v]; return f"{path}{k}: list ×1.37"
                r = walk(v, path + k + ".")
                if r:
                    return r
        elif isinstance(o, list):
            for i, v in enumerate(o):
                r = walk(v, f"{path}[{i}].")
                if r:
                    return r
        return None
    how = walk(p)
    return (p, how) if how else (None, None)


def main():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from concordance.derivation import verify_derivation as vd
    rows = harvest()
    out, seen = [], set()
    for r in rows:
        if r["check"] in seen:
            continue
        seen.add(r["check"])
        dom, pk = r["domain"], r["packet"]
        t = vd([{"id": "g", "domain": dom, "spec": pk}])
        if t["verdict"] != "HOLDS":
            continue
        false_pk, how = _perturb(pk)
        f_ok = False
        if false_pk is not None:
            f = vd([{"id": "g", "domain": dom, "spec": false_pk}])
            f_ok = f["verdict"] == "BROKEN"
        out.append({"check": r["check"], "domain": dom, "true": pk,
                    "false": false_pk if f_ok else None, "perturbation": how if f_ok else None})
    path = os.path.join(ROOT, "data", "check_goldens.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for o in out:
            fh.write(json.dumps(o, default=str) + "\n")
    n_false = sum(1 for o in out if o["false"])
    print(f"{len(rows)} confirmed packets seen in the suite; {len(out)} checks with a TRUE golden; "
          f"{n_false} with a derived FALSE golden -> {path}")


if __name__ == "__main__":
    main()
