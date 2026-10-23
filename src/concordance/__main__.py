"""Run the engine from the command line.

    python -m concordance serve [--host H] [--port N]     HTTP API + MCP at /mcp
    python -m concordance mcp                             MCP server over stdio
    python -m concordance mcp --list-tools
    python -m concordance verify '<json: {steps|mode,params|claim}>'
"""
from __future__ import annotations

import json
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "serve":
        from .http_api import serve
        host, port = "127.0.0.1", 8000
        for j, o in enumerate(argv):
            if o == "--host" and j + 1 < len(argv):
                host = argv[j + 1]
            if o == "--port" and j + 1 < len(argv):
                port = int(argv[j + 1])
        serve(host, port)
        return 0
    if argv[0] == "mcp":
        if "--list-tools" in argv:
            from .mcp.server import list_tools
            for t in list_tools():
                print(t["name"])
            return 0
        from .mcp.server import serve_stdio
        serve_stdio()
        return 0
    if argv[0] == "verify" and len(argv) > 1:
        from .config import EngineConfig
        from .mcp.server import _call_tool
        print(json.dumps(_call_tool("verify", json.loads(argv[1]), EngineConfig()), indent=1, default=str))
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
