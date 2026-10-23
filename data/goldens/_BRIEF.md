You are writing per-check golden test cases for a deterministic verification engine.

Repo: /home/claude/concordance-3 (run everything with `cd /home/claude/concordance-3 && PYTHONPATH=src python3 ...`).
Your assignment file is data/goldens/_assignment_<N>.json: {module: [check names]}. For EACH module in it:
1. Read src/concordance/verifiers/<module>.py — the module docstring documents the packet key and shape;
   each `def verify_<check>(spec)` reads fields with spec.get("...") / spec["..."]; `run(packet)` (or the `_RULES`
   table) shows which fields TRIGGER the check. Some checks take a sub-dict (e.g. spec["hardy_weinberg"]).
2. Write data/goldens/<module>.json exactly in this format:
   {"domain": "<module>", "packet_key": "<ARTIFACT_KEY from run()>",
    "cases": [{"check": "<check name>", "true": {<artifact fields>}, "false": {<same, with ONE claimed value wrong>}}, ...]}
   - "true" must yield CONFIRMED for that check; "false" must yield MISMATCH (a wrong CLAIMED value — not malformed
     input, which only yields ERROR). Compute true values by hand or with python; use the formula in the code.
   - Include EVERY check in your assignment for that module. If a check genuinely cannot be exercised without
     external data or code execution (it returns NOT_APPLICABLE by design), omit it and note it in a "skipped"
     list in the json: "skipped": [{"check": "...", "why": "..."}].
   - For modules whose run() reads several artifact keys, set packet_key to the key your cases use; if cases need
     different keys, make two json files: <module>.json and <module>_2.json (same "domain").
3. VERIFY each case yourself before finishing:
   PYTHONPATH=src python3 -c "
   import json; from concordance.derivation import verify_derivation as vd
   g=json.load(open('data/goldens/<module>.json'))
   for c in g['cases']:
       for lab in ('true','false'):
           r=vd([{'id':'c','domain':g['domain'],'spec':{g['packet_key']:c[lab]}}]); print(c['check'],lab,r['verdict'],r['trail'][0]['detail'][:100])"
   Every true must print HOLDS and every false must print BROKEN. Fix until they do.
4. Do not modify any file under src/. If a verifier is genuinely broken (a true value cannot be confirmed because
   the code is wrong), record it in your final message with the evidence and skip that check.
Final reply: one line per module: "<module>: N cases ok, M skipped" plus any verifier bugs found. Nothing else.
