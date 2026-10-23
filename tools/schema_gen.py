"""Generate (or check) the packet schemas for every registered verifier domain.

    PYTHONPATH=src python tools/schema_gen.py            # write docs/schemas.json + print a summary
    PYTHONPATH=src python tools/schema_gen.py --check    # exit 1 if any domain lacks an artifact key or fields
"""
import json, sys
from concordance import schema, verifiers as V

V._load_plugins()
mods = sorted({v.rsplit(".", 1)[-1] for v in V.VERIFIERS.values()})
out, bad = {}, []
for m in mods:
    s = schema.schema_for(m)
    out[m] = s
    if m == "mathematics":
        continue
    if not s.get("artifact_key") or not s.get("checks"):
        bad.append((m, "no artifact key" if not s.get("artifact_key") else "no checks found"))
if "--check" in sys.argv:
    for m, why in bad:
        print(f"MISSING {m}: {why}")
    print(f"{len(mods) - len(bad)}/{len(mods)} domains have a generated schema")
    sys.exit(1 if bad else 0)
json.dump(out, open("docs/schemas.json", "w"), indent=1, sort_keys=True)
print(f"wrote docs/schemas.json for {len(mods)} domains; {len(bad)} without a full schema: {[m for m, _ in bad]}")
