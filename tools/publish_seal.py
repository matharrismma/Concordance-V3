"""Publish a seal to a transparency log.

    PYTHONPATH=src python tools/publish_seal.py <content_hash> [--key <ed25519 private b64u>] [--out dir] [--rekor]

Writes <hash>.statement.json (in-toto) and <hash>.dsse.json; with --rekor, uploads the DSSE envelope with
`rekor-cli upload --type dsse` if rekor-cli is on PATH, and prints the log index / inclusion URL.
"""
import json, os, shutil, subprocess, sys
from concordance import envelope, __version__

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 2
    h = a[0]
    key = a[a.index("--key") + 1] if "--key" in a else os.environ.get("CONCORDANCE_SIGNING_KEY")
    out = a[a.index("--out") + 1] if "--out" in a else "."
    stmt = envelope.statement(h, engine_version=__version__, public_base=os.environ.get("CONCORDANCE_PUBLIC_BASE", ""))
    env = envelope.dsse(stmt, key)
    os.makedirs(out, exist_ok=True)
    sp, dp = os.path.join(out, f"{h}.statement.json"), os.path.join(out, f"{h}.dsse.json")
    json.dump(stmt, open(sp, "w"), indent=1); json.dump(env, open(dp, "w"), indent=1)
    print("statement:", sp); print("dsse:", dp, "(signed)" if env["signatures"] else "(unsigned)")
    if "--rekor" in a:
        if not shutil.which("rekor-cli"):
            print("rekor-cli not on PATH; install from https://github.com/sigstore/rekor and rerun with --rekor"); return 1
        if not env["signatures"]:
            print("Rekor needs a signed envelope; pass --key"); return 1
        r = subprocess.run(["rekor-cli", "upload", "--type", "dsse", "--artifact", dp], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip()); return r.returncode
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
