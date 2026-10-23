"""The HTTP API — stdlib only. Same calls as the MCP tools, as routes.

    POST /verify        {steps|mode,params|claim} [?seal=0]   -> verdict, trail, seal
    POST /discern       {text}                                 -> proposal
    POST /audit         {text} [?seal=0]                       -> coverage report
    POST /scribe        {drafts, packets, claim_ids}           -> pass report
    GET  /s/<hash>      the sealed record (JSON); GET /s/<hash>?html=1 a human page
    GET  /schema/<domain>, GET /find?q=..., GET /capabilities, GET /ledger/verify, GET /health
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
                      "domain": d.get("domain"), "spec": spec})
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
  {('<form class="recheck">' + fields + '<button type="submit">Re-check with these inputs</button><output></output></form>') if art else '<p class="muted">The packet for this step was not kept beside the seal.</p>'}
</section>""")
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Receipt {esc(h[:12])}</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--ok:#1f7a3a;--bad:#a12626;--line:#ddd}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--mut:#aaa;--line:#333}}}}
body{{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:52rem;padding:1.5rem 1rem}}
h1{{font-size:1.4rem;margin:.2rem 0}} h2{{font-size:1.05rem;margin:1.2rem 0 .3rem}}
code{{word-break:break-all;font-size:.9em}} .muted{{color:var(--mut)}}
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
<p>Content hash <code>{esc(h)}</code>. The JSON at <a href="/s/{esc(h)}">/s/{esc(h)}</a>, hashed canonically with SHA-256, reproduces this hash — that is the whole claim of the seal. Changing inputs below recomputes a fresh verdict; it does not alter this record.</p>
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
