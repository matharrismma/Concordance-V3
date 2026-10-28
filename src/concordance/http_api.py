"""The HTTP API — stdlib only. Same calls as the MCP tools, as routes.

    POST /verify        {steps|mode,params|claim} [?seal=0]   -> verdict, trail, seal
    POST /discern       {text}                                 -> proposal
    POST /audit         {text} [?seal=0]                       -> coverage report
    POST /scribe        {drafts, packets, claim_ids}           -> pass report
    GET  /s/<hash>      the sealed record (JSON); GET /s/<hash>?html=1 a human page
    GET  /schema/<domain>, GET /find?q=..., GET /capabilities, GET /ledger/verify, GET /health
    GET  /seal?hash=<hash>, GET /seals?limit=N        v2-compatible aliases used by the .org app
    POST|GET|DELETE /mcp   Streamable-HTTP MCP transport
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, urlsplit

from .config import EngineConfig
from .mcp import server as _mcp
from .mcp.http import handle_http as _mcp_http

MAX_BODY = 256 * 1024
_CONFIG = EngineConfig()


def _json(status: int, obj: Any) -> Tuple[int, Dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(obj, ensure_ascii=False, default=str).encode()


def _provenance_html(rec: Dict[str, Any]) -> str:
    """One line saying who signed and where it is logged — or that it is self-attested."""
    from html import escape as esc
    att = rec.get("attest") or {}
    env, log = att.get("envelope") or {}, att.get("log") or {}
    if not env:
        return '<p class="muted">Self-attested: content-addressed only; no issuer signature or public log entry.</p>'
    line = f'Signed by issuer <code>{esc(env.get("kid") or "")}</code> (COSE_Sign1, Ed25519).'
    if log and not log.get("pending") and log.get("uuid"):
        line += (f' Logged on Rekor at index <code>{esc(str(log.get("index")))}</code>'
                 f' — <a href="{esc(log.get("url") or "")}/api/v1/log/entries/{esc(log["uuid"])}">entry</a>'
                 f'{", inclusion proof held" if log.get("inclusion_proof") else ""}.')
    else:
        line += f' Log entry pending{(": " + esc(str(log.get("error")))) if log.get("error") else ""}.'
    return f'<p class="muted">{line} Check it yourself with <code>docs/verify_receipt.py</code>.</p>'


def _read_of(rec: Dict[str, Any]) -> str:
    for g in rec.get("gate_results") or []:
        r = (g.get("details") or {}).get("read")
        if r:
            return r
    return "Not a truth engine: a check computes what can be computed and narrows the rest; HOLDS means survived, never proven."


def _budget_html(rec: Dict[str, Any]) -> str:
    """The link budget line: the worst event on the chain, as a fiber tech would read an OTDR summary."""
    from html import escape as esc
    for g in rec.get("gate_results") or []:
        b = (g.get("details") or {}).get("budget")
        if b and b.get("read"):
            return f'<p class="muted">Link budget: {esc(b["read"])}.</p>'
    return ""


def _narrow_html(ref: Dict[str, Any]) -> str:
    """The narrow way for one step: the bands every true claim must lie in, the counterexample if there is
    one, and which refutations were attempted. Empty when the verifier has not yet adopted band()."""
    from html import escape as esc
    if not ref:
        return ""
    def num(x):
        try:
            return f"{float(x):,.6g}"
        except (TypeError, ValueError):
            return esc(str(x))
    def where(b):
        lo, hi = b.get("low"), b.get("high")
        if lo is None and hi is not None:
            return f"be at most <code>{num(hi)}</code>"
        if hi is None and lo is not None:
            return f"be at least <code>{num(lo)}</code>"
        return f"lie in <code>[{num(lo)}, {num(hi)}]</code>"
    rows = "".join(
        f'<li><code>{esc(str(b.get("what")))}</code> must {where(b)}'
        f' — claimed {num(b.get("claimed"))}: <span class="v {"CONFIRMED" if b.get("inside") else "MISMATCH"}">'
        f'{"inside" if b.get("inside") else "outside, off by " + num(b.get("off_by"))}</span></li>'
        for b in ref.get("bands") or [])
    att, sur, cx = len(ref.get("attempted") or []), len(ref.get("survived") or []), ref.get("counterexamples") or []
    line = f"{att} refutation{'s' if att != 1 else ''} attempted, {sur} survived"
    m = ref.get("margin") or {}
    if m.get("read"):
        line += f"; margin: {esc(m['read'])}"
    if cx:
        line += f", {len(cx)} counterexample{'s' if len(cx) != 1 else ''}"
    if ref.get("not_applicable"):
        line += f"; not attempted on this packet: {esc(', '.join(str(n).rsplit('.', 1)[-1] for n in ref['not_applicable']))}"
    return f'<p class="muted">{line}.</p>' + (f'<ul class="bands">{rows}</ul>' if rows else "")


def _receipt_html(rec: Dict[str, Any], h: str) -> bytes:
    """The receipt as a page a person can read — and re-check. Each step's packet (filed beside the seal
    under its spec_hash) is shown as editable inputs; "Re-check" posts the edited packet to /verify with
    seal=0 and shows the fresh verdict. The sealed record itself is never changed by this page."""
    from . import cas as _cas

    def esc(x: Any) -> str:
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    overall = esc(rec.get("overall", ""))
    steps = []
    for vr in rec.get("verifier_results") or []:
        d = vr.get("data") or {}
        spec = _cas.fetch_spec(str(d.get("spec_hash") or "")) or {}
        steps.append({"id": vr.get("name"), "status": vr.get("status"), "detail": vr.get("detail", ""),
                      "domain": d.get("domain"), "spec": spec, "refutations": d.get("refutations") or {}})
    blocks = []
    for n, st in enumerate(steps):
        art_key = next((k for k, v in st["spec"].items() if isinstance(v, dict)), None)
        art = st["spec"].get(art_key) if art_key else st["spec"]
        fields = "".join(
            f'<label>{esc(k)} <input name="{esc(k)}" value="{esc(json.dumps(v) if isinstance(v, (list, dict)) else v)}"></label>'
            for k, v in (art or {}).items())
        blocks.append(f"""
<section class="step" data-domain="{esc(st['domain'] or '')}" data-key="{esc(art_key or '')}" data-wrap="{esc(json.dumps({k: v for k, v in st['spec'].items() if k != art_key}))}">
  <h2>Step {esc(st['id'])} <span class="v {esc(st['status'])}">{esc(st['status'])}</span></h2>
  <p class="detail">{esc(st['detail'])}</p>
  {_narrow_html(st['refutations'])}
  {('<form class="recheck">' + fields + '<button type="submit">Re-check with these inputs</button><output></output></form>') if art else '<p class="muted">The packet for this step was not kept beside the seal.</p>'}
</section>""")
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Receipt {esc(h[:12])}</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--ok:#1f7a3a;--bad:#a12626;--line:#ddd}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333}}}}
body{{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:52rem;padding:1.5rem 1rem}}
h1{{font-size:1.4rem;margin:.2rem 0}} h2{{font-size:1.05rem;margin:1.2rem 0 .3rem}}
code{{word-break:break-all;font-size:.9em}} .muted{{color:var(--mut)}} ul.bands{{margin:.2rem 0 .6rem;padding-left:1.2rem}}
.v{{font-weight:600;padding:.05rem .45rem;border-radius:.3rem;border:1px solid var(--line);font-size:.85rem;vertical-align:middle}}
.v.CONFIRMED,.v.PASS{{color:var(--ok)}} .v.MISMATCH,.v.BROKEN{{color:var(--bad)}}
.step{{border-top:1px solid var(--line);padding-top:.4rem}}
form{{display:grid;grid-template-columns:1fr 1fr;gap:.5rem .9rem;margin:.5rem 0}}
label{{display:flex;flex-direction:column;font-size:.85rem;color:var(--mut)}}
input{{font:inherit;color:var(--fg);background:transparent;border:1px solid var(--line);border-radius:.3rem;padding:.3rem .4rem}}
button{{grid-column:1/-1;justify-self:start;font:inherit;padding:.4rem .8rem;border-radius:.4rem;border:1px solid var(--line);background:transparent;color:var(--fg);cursor:pointer}}
output{{grid-column:1/-1;white-space:pre-wrap;font-size:.9rem}}
@media(max-width:520px){{form{{grid-template-columns:1fr}}}}
</style>
<h1>Sealed record <span class="v {overall}">{overall}</span></h1>
<p class="muted">{esc(_read_of(rec))}</p>
{_budget_html(rec)}
<p>Content hash <code>{esc(h)}</code>. The JSON at <a href="/s/{esc(h)}">/s/{esc(h)}</a>, hashed canonically with SHA-256, reproduces this hash — that is the whole claim of the seal. Changing inputs below recomputes a fresh verdict; it does not alter this record.</p>
{_provenance_html(rec)}
{''.join(blocks)}
<p class="muted">Checks arithmetic and formula application only — never whether a correct result is safe, lawful, or suitable.</p>
<script>
document.querySelectorAll('form.recheck').forEach(f=>{{
  f.addEventListener('submit',async e=>{{
    e.preventDefault(); const sec=f.closest('.step'); const out=f.querySelector('output'); out.textContent='checking…';
    const art={{}}; for(const inp of f.querySelectorAll('input')){{ let v=inp.value.trim(); try{{ v=JSON.parse(v);}}catch(_e){{}} art[inp.name]=v; }}
    const key=sec.dataset.key; let spec; try{{ spec=JSON.parse(sec.dataset.wrap||'{{}}'); }}catch(_e){{ spec={{}}; }}
    if(key) spec[key]=art; else spec=art;
    try{{
      const r=await fetch('/verify?seal=0',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{steps:[{{id:'r',domain:sec.dataset.domain,spec}}]}})}});
      const j=await r.json(); const t=(j.trail&&j.trail[0])||{{}};
      out.textContent=(j.verdict||'?')+' — '+(t.detail||JSON.stringify(j.problems||j).slice(0,300));
    }}catch(err){{ out.textContent='could not reach /verify: '+err; }}
  }});
}});
</script></html>""".encode()


def _document_html(rec: Dict[str, Any], h: str) -> bytes:
    """A document root as a tree: each step, what it rests on, its packet (from the spec sidecar), the
    parents it stands on. Re-check re-runs the WHOLE chain from the edited inputs (seal=0): a change
    upstream is felt downstream, exactly as in the sealed derivation."""
    from . import cas as _cas, compose as _compose

    def esc(x: Any) -> str:
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    steps = rec.get("steps") or []
    labels = rec.get("labels") or {}
    blocks = []
    for st in steps:
        spec = _cas.fetch_spec(str(st.get("spec_hash") or "")) or {}
        art_key = next((k for k, v in spec.items() if isinstance(v, dict)), None)
        art = spec.get(art_key) if art_key else spec
        fields = "".join(
            f'<label>{esc(k)} <input name="{esc(k)}" value="{esc(json.dumps(v) if isinstance(v, (list, dict)) else v)}"></label>'
            for k, v in (art or {}).items())
        rests = ", ".join(esc(u) for u in st.get("uses") or []) or "—"
        blocks.append(f"""
<section class="step" data-id="{esc(st.get('id'))}" data-domain="{esc(st.get('domain') or '')}" data-key="{esc(art_key or '')}" data-wrap="{esc(json.dumps({k: v for k, v in spec.items() if k != art_key}))}">
  <h2>{esc(st.get('id'))} <span class="v {esc(st.get('status'))}">{esc(st.get('status'))}</span> <small>{esc(labels.get(str(st.get('id')), ''))}</small></h2>
  <p class="muted">rests on: {rests} · domain {esc(st.get('domain'))} · packet <code>{esc(str(st.get('spec_hash') or '')[:12])}</code></p>
  <p class="detail">{esc(st.get('detail', ''))}</p>
  <div class="fields">{fields}</div>
</section>""")
    parents = ""
    for p in rec.get("parents") or []:
        pr = _compose.fetch_document(p)
        parents += f'<li><a href="/s/{esc(p)}?html=1">{esc(pr.get("title") if pr else p[:16] + "…")}</a> <span class="v {esc(pr.get("verdict") if pr else "")}">{esc(pr.get("verdict") if pr else "seal")}</span></li>'
    verdict = esc(rec.get("verdict", ""))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(rec.get('title') or 'Document')} — {esc(h[:12])}</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--ok:#1f7a3a;--bad:#a12626;--line:#ddd}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333}}}}
body{{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:54rem;padding:1.5rem 1rem}}
h1{{font-size:1.4rem;margin:.2rem 0}} h2{{font-size:1.05rem;margin:1.1rem 0 .2rem}} h2 small{{font-weight:400;color:var(--mut)}}
code{{word-break:break-all;font-size:.9em}} .muted{{color:var(--mut);margin:.1rem 0}}
.v{{font-weight:600;padding:.05rem .45rem;border-radius:.3rem;border:1px solid var(--line);font-size:.85rem;vertical-align:middle}}
.v.CONFIRMED,.v.HOLDS,.v.PASS{{color:var(--ok)}} .v.MISMATCH,.v.BROKEN{{color:var(--bad)}}
.step{{border-left:3px solid var(--line);padding-left:.8rem;margin:.6rem 0}}
.fields{{display:grid;grid-template-columns:1fr 1fr;gap:.4rem .9rem;margin:.4rem 0}}
label{{display:flex;flex-direction:column;font-size:.85rem;color:var(--mut)}}
input{{font:inherit;color:var(--fg);background:transparent;border:1px solid var(--line);border-radius:.3rem;padding:.3rem .4rem}}
button{{font:inherit;padding:.45rem .9rem;border-radius:.4rem;border:1px solid var(--line);background:transparent;color:var(--fg);cursor:pointer;margin-top:.8rem}}
#out{{white-space:pre-wrap;font-size:.9rem;margin-top:.6rem}} ul{{padding-left:1.2rem}}
@media(max-width:520px){{.fields{{grid-template-columns:1fr}}}}
</style>
<h1>{esc(rec.get('title') or 'Document')} <span class="v {verdict}">{verdict}</span></h1>
<p>Root <code>{esc(h)}</code> — the SHA-256 of a record naming every step's packet hash, status and dependencies, the derivation seal <code>{esc(str(rec.get('derivation_seal') or '')[:12])}</code>, and the parents below. Re-fetch <a href="/s/{esc(h)}">the JSON</a>, re-hash it, walk the tree.</p>
{_provenance_html(rec)}
{('<p class="muted">Stands on:</p><ul>' + parents + '</ul>') if parents else ''}
{''.join(blocks)}
<button id="recheck">Re-check the whole chain with these inputs</button>
<div id="out"></div>
<p class="muted">Checks arithmetic and formula application only — never whether a correct result is safe, lawful, or suitable. Re-checking never alters this record.</p>
<script>
const USES = {json.dumps({str(st.get('id')): list(st.get('uses') or []) for st in steps})};
const BINDS = {json.dumps(rec.get('binds') or {})};
const ORIG = {json.dumps([{"id": st.get("id"), "domain": st.get("domain")} for st in steps])};
document.getElementById('recheck').addEventListener('click', async () => {{
  const out = document.getElementById('out'); out.textContent = 'checking…';
  const steps = [];
  for (const sec of document.querySelectorAll('.step')) {{
    const art = {{}}; for (const inp of sec.querySelectorAll('input')) {{ let v = inp.value.trim(); try {{ v = JSON.parse(v); }} catch (_e) {{}} art[inp.name] = v; }}
    let spec; try {{ spec = JSON.parse(sec.dataset.wrap || '{{}}'); }} catch (_e) {{ spec = {{}}; }}
    if (sec.dataset.key) spec[sec.dataset.key] = art; else spec = art;
    const step = {{ id: sec.dataset.id, domain: sec.dataset.domain, spec }};
    if ((USES[sec.dataset.id] || []).length) step.uses = USES[sec.dataset.id];
    if (BINDS[sec.dataset.id]) step.bind = BINDS[sec.dataset.id];
    steps.push(step);
  }}
  try {{
    const r = await fetch('/verify?seal=0', {{ method: 'POST', headers: {{ 'content-type': 'application/json' }}, body: JSON.stringify({{ steps }}) }});
    const j = await r.json();
    out.textContent = [j.verdict || '?'].concat((j.trail || []).map(t => '  ' + t.id + ': ' + t.status + ' - ' + (t.detail || ''))).join(String.fromCharCode(10)) + (j.problems ? ' ' + JSON.stringify(j.problems).slice(0, 400) : '');
  }} catch (err) {{ out.textContent = 'could not reach /verify: ' + err; }}
}});
</script></html>""".encode()


def route(method: str, path: str, query: Dict[str, Any], body: Dict[str, Any], headers: Any, raw: bytes):
    seal_on = str(query.get("seal", ["1"])[0]) not in ("0", "false")
    if path == "/health":
        return _json(200, {"ok": True})
    if path.startswith("/mcp"):
        return _mcp_http(method, headers, raw, _CONFIG)
    if method == "GET":
        if path == "/capabilities":
            return _json(200, _mcp._call_tool("capabilities", {}, _CONFIG))
        if path == "/ledger/verify":
            return _json(200, _mcp._call_tool("ledger_verify", {}, _CONFIG))
        if path == "/seal":                                   # v2-compatible: GET /seal?hash=<h>
            h = str(query.get("hash", [""])[0])
            rec = _mcp._call_tool("seal_fetch", {"hash": h}, _CONFIG)
            return _json(404 if "error" in rec else 200, rec)
        if path == "/seals":                                  # v2-compatible: GET /seals?limit=N
            from . import ledger as _ledger
            lim = max(1, min(200, int(query.get("limit", ["20"])[0] or 20)))
            entries = [e for e in _ledger.list_precedents() if len(str(e.get("record_hash") or "")) == 64][-lim:][::-1]
            return _json(200, {"note": "most recent sealed records (newest first); record_hash is the CAS content hash",
                               "count": len(entries),
                               "seals": [{"content_hash": e.get("record_hash"), "summary": e.get("summary"),
                                          "sealed_at": e.get("sealed_at"), "cite_url": f"/s/{e.get('record_hash')}"}
                                         for e in entries]})
        if path == "/find":
            return _json(200, _mcp._call_tool("find_verifier", {"query": query.get("q", [""])[0]}, _CONFIG))
        m = re.fullmatch(r"/schema/([a-z_]+)", path)
        if m:
            from . import schema as _schema
            return _json(200, _schema.schema_for(m.group(1)))
        m = re.fullmatch(r"/s/([0-9a-f]{64})", path)
        if m:
            rec = _mcp._call_tool("seal_fetch", {"hash": m.group(1)}, _CONFIG)
            if "error" in rec:
                return _json(404, rec)
            if query.get("html"):
                if rec.get("kind") == "document":
                    return 200, {"Content-Type": "text/html; charset=utf-8"}, _document_html(rec, m.group(1))
                return 200, {"Content-Type": "text/html; charset=utf-8"}, _receipt_html(rec, m.group(1))
            return _json(200, rec)
        if path == "/":
            return _json(200, {"engine": "concordance", "routes": __doc__.strip().splitlines()[2:]})
        return _json(404, {"error": "not found"})
    if method == "POST":
        name = path.strip("/")
        if name in ("verify", "discern", "audit", "scribe"):
            args = dict(body)
            if name in ("verify", "audit"):
                args["seal"] = seal_on and args.get("seal", True) is not False
            try:
                return _json(200, _mcp._call_tool(name, args, _CONFIG))
            except Exception as e:  # noqa: BLE001
                return _json(500, {"error": "tool error", "code": "INTERNAL_FAILURE", "detail": type(e).__name__})
        return _json(404, {"error": "not found"})
    return 405, {"Allow": "GET, POST"}, b""


class Handler(BaseHTTPRequestHandler):
    server_version = "concordance/3"

    def _serve(self, method: str) -> None:
        u = urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, MAX_BODY)) if n else b""
        try:
            body = json.loads(raw or b"{}") if method == "POST" and not u.path.startswith("/mcp") else {}
            if not isinstance(body, dict):
                body = {}
        except ValueError:
            body = {}
        status, hdrs, out = route(method, u.path, parse_qs(u.query), body, self.headers, raw)
        self.send_response(status)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):     # noqa: N802
        self._serve("GET")

    def do_POST(self):    # noqa: N802
        self._serve("POST")

    def do_DELETE(self):  # noqa: N802
        self._serve("DELETE")

    def log_message(self, *a):  # quiet
        return


def serve(host: str = "127.0.0.1", port: int = 8000, background: bool = False):
    srv = ThreadingHTTPServer((host, port), Handler)
    if background:
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv
    print(f"concordance API on http://{host}:{port}/  (MCP at /mcp)")
    srv.serve_forever()


__all__ = ["serve", "route", "Handler"]
