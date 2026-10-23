#!/usr/bin/env python3
"""publish_seals.py — mint envelopes and push pending log entries for held seals.

    python3 tools/publish_seals.py [--limit N] [--dry-run] [--hash <content_hash> ...]

Walks the attest sidecars (data/cas/attest/*.json) plus, with --all-ledger, every ledger record, and for
each seal without a settled log entry: mints the COSE_Sign1 envelope (if missing) and publishes it to
Rekor. Idempotent — a seal already logged is skipped; a 409 from Rekor resolves to the existing entry.
Needs CONCORDANCE_ISSUER_KEY. Exit 0 when nothing is left pending, 2 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from concordance import cas, ledger, transparency as T  # noqa: E402


def candidates(all_ledger: bool, explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    seen: dict[str, None] = {}
    side = cas._cas_dir() / "attest"
    if side.exists():
        for p in sorted(side.glob("*.json")):
            seen.setdefault(p.stem, None)
    if all_ledger:
        for e in ledger.list_precedents():
            h = e.get("record_hash")
            if h and len(str(h)) == 64:
                seen.setdefault(h, None)
    return list(seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all-ledger", action="store_true", help="also consider every ledgered seal, not just sidecars")
    ap.add_argument("--hash", action="append", default=[])
    a = ap.parse_args()
    st = T.status()
    if not st["issuer_key_configured"]:
        print("no CONCORDANCE_ISSUER_KEY configured; nothing can be signed", file=sys.stderr)
        return 2
    done = pending = skipped = 0
    for h in candidates(a.all_ledger, a.hash)[: a.limit]:
        side = T._sidecar(h) or {}
        log = side.get("log") or {}
        if log and not log.get("pending"):
            skipped += 1
            continue
        if a.dry_run:
            print(f"would publish {h[:16]}…  ({log.get('error') or 'no attempt yet'})")
            pending += 1
            continue
        out = T.attest(h, publish_log=True)
        lg = out.get("log") or {}
        if lg.get("pending") or "error" in out:
            pending += 1
            print(f"pending   {h[:16]}…  {lg.get('error') or out.get('error')}")
        else:
            done += 1
            print(f"published {h[:16]}…  rekor index {lg.get('index')}")
    print(json.dumps({"published": done, "pending": pending, "already_logged": skipped, "kid": st["kid"]}))
    return 0 if pending == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
