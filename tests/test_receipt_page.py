"""The receipt page: the sealed packet is filed beside the seal under its spec_hash; the page shows the
inputs and re-checks without touching the record; `_spec` never leaves the engine."""
import json
from concordance import cas, http_api, receipts
from concordance.config import EngineConfig
from concordance.mcp.server import _call_tool

C = EngineConfig()
STEP = {"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
    "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240, "claimed_monthly_payment": 75917.93}}}


def test_spec_sidecar_matches_the_trail_spec_hash_and_is_not_returned():
    r = _call_tool("verify", {"steps": [STEP]}, C)
    assert r["verdict"] == "HOLDS" and "_spec" not in json.dumps(r)
    sh = r["trail"][0]["spec_hash"]
    assert cas.fetch_spec(sh) == STEP["spec"]


def test_receipt_page_shows_inputs_and_recheck_form():
    r = _call_tool("verify", {"steps": [STEP]}, C)
    rec = _call_tool("seal_fetch", {"hash": r["seal"]["content_hash"]}, C)
    html = http_api._receipt_html(rec, r["seal"]["content_hash"]).decode()
    assert 'name="annual_rate" value="0.045"' in html and "Re-check" in html
    assert "/verify?seal=0" in html                      # re-checks never mint


def test_receipt_page_stands_on_matches_the_trace_for_a_reverse_listed_chain():
    # c uses b, b uses a, listed top-down: the page must read the floor by id, as the trace does, not by
    # listed order (which once showed c standing on b alone). Nothing is sealed: the record is built in memory.
    chain = [{**STEP, "id": "c", "uses": ["b"]}, {**STEP, "id": "b", "uses": ["a"]}, {**STEP, "id": "a"}]
    r = _call_tool("verify", {"steps": chain, "seal": False}, C)
    assert r["verdict"] == "HOLDS" and r.get("seal") is None
    floor = {e["id"]: e["stands_on"] for e in r["trace"]["events"]}
    assert floor == {"c": ["b", "a"], "b": ["a"], "a": []}
    html = http_api._receipt_html(receipts.record_from_derivation(r, domain="real_estate").to_dict(), "0" * 64).decode()
    for sid, under in floor.items():
        assert f"<h2>Step {sid} " in html
        head = html.split(f"<h2>Step {sid} ")[1].split("</h2>")[0]
        assert head.endswith(("stands on " + ", ".join(under) if under else "· floor") + "</span>"), head


def _stands_on_at_d47d692(steps):
    """The page's own formula at d47d692 (http_api.py:126-135), frozen verbatim as the oracle for what the page
    showed before it read the trace: each step's floor built from the steps listed before it, keyed by id."""
    stands: dict = {}
    out = []
    for st in steps:
        floor: list = []
        for u in st["uses"]:
            for x in [u] + stands.get(u, []):
                if x not in floor:
                    floor.append(x)
        stands[st["id"]] = floor
        out.append(floor)
    return out


def _unsealed_page(chain):
    """Verify `chain` with seal=False (nothing is stored), build its record in memory and render the page.
    Returns the result, the steps as the page reads them from the record, and the page's step headers in order."""
    r = _call_tool("verify", {"steps": chain, "seal": False}, C)
    assert r.get("seal") is None
    rec = receipts.record_from_derivation(r, domain="real_estate").to_dict()
    html = http_api._receipt_html(rec, "0" * 64).decode()
    listed = [{"id": vr.get("name"), "uses": list((vr.get("data") or {}).get("uses") or [])}
              for vr in rec["verifier_results"]]
    return r, listed, [h.split("</h2>")[0] for h in html.split("<h2>Step ")[1:]]


def _shown(head):
    """One step header read back: (the step's id, the ids it says the step stands on; [] for the floor)."""
    tail = head.rsplit('<span class="muted">', 1)[1]
    assert tail.endswith("</span>"), head
    tail = tail[:-len("</span>")]
    if tail.endswith(" · floor"):
        return head.split(" ", 1)[0], []
    assert " · stands on " in tail, head
    return head.split(" ", 1)[0], tail.split(" · stands on ", 1)[1].split(", ")


def _trace(r):
    return [(e["id"], e["stands_on"]) for e in r["trace"]["events"]]


def test_receipt_page_renders_a_sorted_chain_of_unique_ids_exactly_as_at_d47d692():
    # [a, b uses a, c uses b]: every id carried by one step, each listed after what it uses. Reading the floor
    # from the trace changes nothing here: the headers are pinned whole, and equal the old formula's reading.
    chain = [{**STEP, "id": "a"}, {**STEP, "id": "b", "uses": ["a"]}, {**STEP, "id": "c", "uses": ["b"]}]
    r, listed, heads = _unsealed_page(chain)
    assert r["verdict"] == "HOLDS"
    v = '<span class="v CONFIRMED">CONFIRMED</span> <span class="muted">applied'
    assert heads == [f"a {v} · floor</span>", f"b {v} · stands on a</span>", f"c {v} · stands on b, a</span>"]
    assert [_shown(h)[1] for h in heads] == _stands_on_at_d47d692(listed) == [f for _, f in _trace(r)]
    # wider, still sorted with unique ids: steps using several, so first-occurrence order and dedup are read too
    wide = [{**STEP, "id": "a"}, {**STEP, "id": "b"}, {**STEP, "id": "c", "uses": ["a", "b"]},
            {**STEP, "id": "d", "uses": ["c", "a"]}, {**STEP, "id": "e", "uses": ["d"]}]
    r, listed, heads = _unsealed_page(wide)
    assert [_shown(h) for h in heads] == [("a", []), ("b", []), ("c", ["a", "b"]), ("d", ["c", "a", "b"]),
                                          ("e", ["d", "c", "a", "b"])]
    assert [_shown(h)[1] for h in heads] == _stands_on_at_d47d692(listed) == [f for _, f in _trace(r)]


def test_receipt_page_repeated_id_stands_on_reads_as_the_trace():
    # [x, a, a uses x, b uses a]: two steps carry a, so b's a names no one step and the trace walks it no
    # further: b stands on a. An intended change: at d47d692 the page kept the last a listed (b on a, x).
    chain = [{**STEP, "id": "x"}, {**STEP, "id": "a"}, {**STEP, "id": "a", "uses": ["x"]},
             {**STEP, "id": "b", "uses": ["a"]}]
    r, listed, heads = _unsealed_page(chain)
    assert _trace(r) == [("x", []), ("a", []), ("a", ["x"]), ("b", ["a"])]
    assert [_shown(h) for h in heads] == _trace(r)
    assert heads[3].endswith(" · stands on a</span>"), heads[3]
    assert _stands_on_at_d47d692(listed)[3] == ["a", "x"]          # what the page showed for b at d47d692


def test_receipt_page_cycle_stands_on_reads_as_the_trace():
    # [a uses b, b uses a]: neither step is ever placed, and the trace names what each reaches, itself included:
    # a stands on b, a. An intended change: at d47d692 the page read b's floor before b was listed (a on b).
    chain = [{**STEP, "id": "a", "uses": ["b"]}, {**STEP, "id": "b", "uses": ["a"]}]
    r, listed, heads = _unsealed_page(chain)
    assert _trace(r) == [("a", ["b", "a"]), ("b", ["a", "b"])]
    assert [_shown(h) for h in heads] == _trace(r)
    assert heads[0].endswith(" · stands on b, a</span>"), heads[0]
    assert _stands_on_at_d47d692(listed) == [["b"], ["a", "b"]]   # what the page showed at d47d692


def test_recheck_route_with_seal_off_returns_fresh_verdict_without_sealing():
    status, _, body = http_api.route("POST", "/verify", {"seal": ["0"]},
                                     {"steps": [{"id": "r", "domain": "real_estate", "spec": {"RE_VERIFY": {
                                         **STEP["spec"]["RE_VERIFY"], "annual_rate": 0.05}}}]}, {}, b"")
    j = json.loads(body)
    assert status == 200 and j["verdict"] == "BROKEN" and j.get("seal") is None
