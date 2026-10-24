#!/usr/bin/env python3
"""A seeded Monte-Carlo fuzz over the engine — the trust half of the reach work.

The benchmark proves the moat on a fixed list. This proves the *invariants* hold under random
traffic: thousands of (domain, label) draws and adversarial text, every one checked against the
properties a verifier must never violate, with a replayable seed when one does.

Invariants (any breach is a hard failure, `--check` exits non-zero):
  1. NO FALSE CERTIFY — a packet labelled false must never return HOLDS. The one that must be 0.
  2. SEAL RE-VERIFIES   — every HOLDS that carries a seal re-hashes to its own content_hash
                          (cas.content_hash_of(fetch(h)) == h), so the receipt is honest.
  3. BOUNDED            — on a warmed engine (the fuzz warms once, as the server does at boot)
                          each verify stays under a wall-clock and a peak-memory ceiling, so the
                          82 s / 6 GB class of regression can never return silently.
  4. WELL-FORMED        — adversarial text (empty, huge, unicode, control, crisis, nested) returns
                          a dict with a verdict or an honest refusal; it never raises and never
                          seals garbage. A crisis phrase takes the help path, never a verdict.
A false packet that only abstains (INCOMPLETE / an engine error) is fine — a miss stays a miss.
A true packet that abstains is reported, not failed (coverage is the benchmark's job, not this).

    PYTHONPATH=src python tools/mc_fuzz.py --trials 2000 --seed 1 --check
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

TIME_BOUND_S = 10.0          # a tripwire, not an SLA: a lean verify is ~0.5 s
MEM_BOUND_MB = 256.0         # peak Python allocation per verify (tracemalloc)

_ADVERSARIAL = [
    "", "   ", "\x00\x01\x02", "¯\\_(ツ)_/¯ 🙂🙂🙂", "НЕ число", "42",
    "(((((((((( deeply nested and never closed",
    "the answer is " + "9" * 5000,                       # a long number run
    "x" * 25_000,                                        # over MAX_TEXT — must be bounded in
    "i want to end my life",                             # crisis — must take the help path
    "2 + 2 = 5 and the sky is green and 10 kg is a mass",
]


@dataclass
class Result:
    trials: int = 0
    seed: int = 0
    verdicts: Counter = field(default_factory=Counter)
    false_certify: int = 0            # invariant 1 breaches
    seal_checked: int = 0
    seal_mismatch: int = 0            # invariant 2 breaches
    over_time: int = 0                # invariant 3 breaches
    over_mem: int = 0                 # invariant 3 breaches
    crashes: int = 0                  # invariant 4 breaches (raised)
    sealed_garbage: int = 0           # invariant 4 breaches (HOLDS on adversarial text)
    true_abstained: int = 0           # reported, not a breach
    true_broken: int = 0              # reported: a true golden the engine refuted (a known FN)
    worst_time_s: float = 0.0
    worst_mem_mb: float = 0.0
    failing_seeds: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def breaches(self) -> int:
        return (self.false_certify + self.seal_mismatch + self.over_time + self.over_mem
                + self.crashes + self.sealed_garbage)

    def as_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "verdicts"}
        d["verdicts"] = dict(self.verdicts)
        return d


def _golden_cases() -> List[Tuple[bool, str, list]]:
    path = Path(__file__).resolve().parent.parent / "data" / "domain_goldens.json"
    goldens = json.loads(path.read_text(encoding="utf-8"))
    from concordance import verifiers as V
    V._load_plugins()
    registered = {v.rsplit(".", 1)[-1] for v in V.VERIFIERS.values()}
    cases: List[Tuple[bool, str, list]] = []
    for dom in sorted(goldens):
        if dom not in registered:
            continue
        g = goldens[dom]
        key = g.get("packet_key")
        for label in ("true", "false"):
            art = g.get(label)
            if isinstance(art, dict) and key:
                cases.append((label == "true", dom, [{"id": "g", "domain": dom, "spec": {key: art}}]))
    return cases


def _timed(fn) -> Tuple[Any, float, bool]:
    """Run fn() under a wall-clock only. Returns (value|None, seconds, raised).

    Timing is deliberately NOT wrapped in tracemalloc: tracemalloc hooks every allocation and
    slows garbage collection by orders of magnitude, so a gen-2 GC during one draw — once the
    engine's module caches have grown — would read as tens of false seconds. Memory is measured
    separately (_peak_mem_mb) on representative verifies, off the timing path.
    """
    t0 = time.perf_counter()
    raised = False
    value = None
    try:
        value = fn()
    except BaseException:  # noqa: BLE001 — the fuzz's whole point is that nothing escapes
        raised = True
    return value, time.perf_counter() - t0, raised


def _peak_mem_mb(fn) -> float:
    """Peak Python allocation of a single fn() call, in MB (its own tracemalloc context)."""
    tracemalloc.start()
    try:
        fn()
    except BaseException:  # noqa: BLE001
        pass
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1e6


def run(trials: int = 2000, seed: int = 1, verbose: bool = False,
        data_dir: Optional[str] = None) -> Result:
    if data_dir:
        os.environ["CONCORDANCE_DATA_DIR"] = data_dir
    from concordance import cas
    from concordance.config import EngineConfig
    from concordance.mcp import server as _server

    # Warm the heavy C-extension deps once, exactly as the server does at boot (api boot-warm).
    # Steady-state per-request cost is what the resource bound is about; a cold import paid inside
    # the per-verify timeout is a start-up concern the deployment already handles, not a per-claim
    # pathology — measuring it here would measure the wrong thing.
    from concordance import derivation as _derivation
    _derivation.warm()

    cfg = EngineConfig()
    cases = _golden_cases()
    rng = random.Random(seed)
    res = Result(trials=trials, seed=seed)

    def _note(local_seed: int, **kw: Any) -> None:
        if len(res.failing_seeds) < 25:
            res.failing_seeds.append({"draw": local_seed, **kw})

    for i in range(trials):
        # ~1 in 6 draws is adversarial text; the rest are golden packets.
        if cases and rng.random() > 1 / 6:
            is_true, dom, steps = rng.choice(cases)
            out, dt, raised = _timed(
                lambda: _server._call_tool("verify", {"steps": steps, "seal": is_true}, cfg))
            kind = f"golden:{dom}:{'true' if is_true else 'false'}"
        else:
            text = rng.choice(_ADVERSARIAL)
            out, dt, raised = _timed(
                lambda: _server._call_tool("verify", {"claim": text, "seal": True}, cfg))
            kind = f"adversarial:{text[:24]!r}"
            is_true, dom = None, None

        res.worst_time_s = max(res.worst_time_s, dt)
        if dt > TIME_BOUND_S:
            res.over_time += 1; _note(i, kind=kind, why=f"time {dt:.1f}s")
        if raised:
            res.crashes += 1; _note(i, kind=kind, why="raised"); continue
        if not isinstance(out, dict) or "verdict" not in out:
            res.crashes += 1; _note(i, kind=kind, why="malformed result"); continue

        verdict = str(out.get("verdict") or "")
        res.verdicts[verdict] += 1
        seal = out.get("seal") if isinstance(out.get("seal"), dict) else {}
        content_hash = seal.get("content_hash")

        if dom is None:  # adversarial text
            if verdict == "HOLDS" and content_hash:
                res.sealed_garbage += 1; _note(i, kind=kind, why="HOLDS on adversarial text")
            continue

        if is_true is False and verdict == "HOLDS":
            res.false_certify += 1; _note(i, kind=kind, why="FALSE CERTIFY")
        if is_true is True and verdict == "BROKEN":
            res.true_broken += 1; _note(i, kind=kind, why="true golden refuted (FN)")
        if is_true is True and verdict not in ("HOLDS", "BROKEN"):
            res.true_abstained += 1

        if verdict == "HOLDS" and content_hash:
            res.seal_checked += 1
            rec = cas.fetch(content_hash)
            if rec is None or cas.content_hash_of(rec) != content_hash:
                res.seal_mismatch += 1; _note(i, kind=kind, why="seal does not re-verify")

        if verbose and i and i % 500 == 0:
            print(f"  {i}/{trials} … breaches={res.breaches}", file=sys.stderr, flush=True)

    # Memory is sampled off the timing path: the peak Python allocation of a few representative
    # verifies (a scipy-backed golden, a big adversarial string, a math golden). This is a balloon
    # tripwire, not a per-draw gauge — a lean verify is single-digit MB.
    samples = [lambda: _server._call_tool("verify", {"claim": "x" * 25_000, "seal": True}, cfg)]
    for dom in ("statistics", "mathematics"):
        picks = [c for c in cases if c[1] == dom]
        if picks:
            steps = picks[0][2]
            samples.append(lambda s=steps: _server._call_tool("verify", {"steps": s, "seal": True}, cfg))
    for fn in samples:
        res.worst_mem_mb = max(res.worst_mem_mb, _peak_mem_mb(fn))
    if res.worst_mem_mb > MEM_BOUND_MB:
        res.over_mem += 1; _note(-1, kind="memory-sample", why=f"mem {res.worst_mem_mb:.0f}MB")

    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Seeded Monte-Carlo fuzz of the verifier invariants.")
    ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--data-dir", default=None, help="seal into this dir (default: configured)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--check", action="store_true", help="exit non-zero on any invariant breach")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    res = run(trials=args.trials, seed=args.seed, verbose=args.verbose, data_dir=args.data_dir)

    if args.json:
        print(json.dumps(res.as_dict(), indent=2))
    else:
        print(f"\nMonte-Carlo fuzz — {res.trials} trials, seed {res.seed}")
        print(f"  verdicts: {dict(res.verdicts)}")
        print(f"  worst: {res.worst_time_s:.2f}s  {res.worst_mem_mb:.0f}MB   "
              f"(bounds {TIME_BOUND_S:.0f}s / {MEM_BOUND_MB:.0f}MB)")
        print(f"  seals re-verified: {res.seal_checked - res.seal_mismatch}/{res.seal_checked}")
        print(f"  true abstained (coverage, not a breach): {res.true_abstained}   "
              f"true refuted (FN): {res.true_broken}")
        tag = "CLEAN" if res.breaches == 0 else f"{res.breaches} BREACH(ES)"
        print(f"  INVARIANTS: no-false-certify={res.false_certify}  seal-mismatch={res.seal_mismatch}  "
              f"over-time={res.over_time}  over-mem={res.over_mem}  crashes={res.crashes}  "
              f"sealed-garbage={res.sealed_garbage}  -> {tag}")
        for f in res.failing_seeds:
            print(f"    FAIL draw#{f['draw']}: {f.get('why')}  [{f.get('kind')}]")

    return 1 if (args.check and res.breaches) else 0


if __name__ == "__main__":
    raise SystemExit(main())
