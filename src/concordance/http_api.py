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
    def esc(s: Any) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    rows = "".join(f"<tr><th>{esc(k)}</th><td><pre>{esc(json.dumps(v, indent=1, default=str) if isinstance(v, (dict, list)) else v)}</pre></td></tr>"
                   for k, v in rec.items())
    return f"""<!doctype html><meta charset="utf-8"><title>Receipt {esc(h[:12])}</title>
<style>body{{font:15px/1.5 system-ui;margin:2rem auto;max-width:56rem;padding:0 1rem}}th{{text-align:left;vertical-align:top;padding:.3rem .8rem .3rem 0;white-space:nowrap}}pre{{margin:0;white-space:pre-wrap}}code{{word-break:break-all}}</style>
<h1>Sealed record</h1><p>Content hash <code>{esc(h)}</code>. Re-hash the JSON at <a href="/s/{esc(h)}">/s/{esc(h)}</a> (SHA-256 of the canonical record) to confirm it reproduces this hash.</p>
<table>{rows}</table>""".encode()


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
