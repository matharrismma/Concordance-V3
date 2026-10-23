# Deploying V3 beside v2

Three steps on the box (`nh@5.78.186.55`), each reversible:

1. **Engine** — `bash deploy/install.sh` (clones/updates `/home/nh/concordance-3`, builds the venv, runs the
   gates, installs `nh-v3.service` on `:8020`, health-checks; rolls back on any failure).
2. **Caddy** — paste `deploy/Caddyfile.v3.snippet` into the `route {}` of `api.narrowhighway.com` above the
   `:8002` catch-all, then `sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`.
   `/verify`, `/s/<hash>`, `/schema/*`, … now hit V3; everything else still hits v2. `/mcp` stays on v2's MCP
   host until the witness app registers its tools on top of V3; V3's MCP is at `/v3/mcp` meanwhile.
3. **Witness app** — add `Environment=NH_VERIFY_URL=http://127.0.0.1:8020` to `nh-org.service`
   (`witness` commit 9d89231 reads it), `sudo systemctl daemon-reload && sudo systemctl restart nh-org`.
   Receipts minted from narrowhighway.org are now V3 seals citing `https://narrowhighway.org/s/<hash>`, which
   the app proxies back to V3.

Verify from anywhere:
```
curl -s https://api.narrowhighway.com/capabilities | jq .tools.count        # 8
curl -s https://api.narrowhighway.com/verify -d '{"steps":[{"id":"m","domain":"real_estate","spec":{"RE_VERIFY":{"loan_principal":12000000,"annual_rate":0.045,"loan_term_months":240,"claimed_monthly_payment":75917.93}}}]}' | jq .verdict
```

Rollback: `sudo systemctl disable --now nh-v3`, remove the Caddy block, drop `NH_VERIFY_URL`. The v2 engine
never stopped serving `/verify`, so nothing is lost but V3's ledger entries (kept in `/home/nh/concordance-3/data`).
