#!/usr/bin/env bash
# Install or update Concordance V3 on the box. Idempotent. Run AS nh (or: sudo -u nh bash deploy/install.sh).
#
#   curl -fsSL https://raw.githubusercontent.com/matharrismma/Concordance-V3/main/deploy/install.sh | bash
#   # or, from a checkout:  bash deploy/install.sh
#
# What it does: clone/pull /home/nh/concordance-3 at the tag or branch in $REF (default: main), build the venv,
# run the gates (suite + benchmark --check + schema --check), install nh-v3.service, restart, health-check on
# :8020. If the gates or the health check fail, the previous checkout is restored and the old unit left running.
set -euo pipefail
REF="${REF:-main}"
DEST="${DEST:-/home/nh/concordance-3}"
REPO="https://github.com/matharrismma/Concordance-V3"
PORT="${PORT:-8020}"
PREV="$DEST.prev"

echo "== Concordance V3 install ($REF -> $DEST)"
if [ -d "$DEST/.git" ]; then
  rm -rf "$PREV"; cp -a "$DEST" "$PREV"
  git -C "$DEST" fetch -q origin
  git -C "$DEST" checkout -q "$REF"
  git -C "$DEST" pull -q --ff-only origin "$REF" 2>/dev/null || true
else
  git clone -q --branch "$REF" "$REPO" "$DEST"
fi
cd "$DEST"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[math,scribe,signing,dev]"

rollback() {
  echo "!! gate failed — restoring previous checkout"
  if [ -d "$PREV" ]; then rm -rf "$DEST"; mv "$PREV" "$DEST"; fi
  exit 1
}
echo "== gates"
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider >/tmp/nh-v3-pytest.log 2>&1 || { tail -5 /tmp/nh-v3-pytest.log; rollback; }
PYTHONPATH=src .venv/bin/python tools/benchmark.py --check || rollback
PYTHONPATH=src .venv/bin/python tools/schema_gen.py --check || rollback
PYTHONPATH=src .venv/bin/python tools/benchmark.py --json > data/benchmark_last.json || rollback

echo "== service"
if command -v sudo >/dev/null && [ -w /etc/systemd/system ] || sudo -n true 2>/dev/null; then
  sudo cp deploy/nh-v3.service /etc/systemd/system/nh-v3.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now nh-v3
  sudo systemctl restart nh-v3
else
  echo "   (no sudo: copy deploy/nh-v3.service to /etc/systemd/system and enable it yourself)"
fi

echo "== health"
for i in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    curl -fsS "http://127.0.0.1:$PORT/capabilities" | .venv/bin/python -c 'import json,sys; c=json.load(sys.stdin); print("   up:", c["verifiers"]["modules"], "verifier modules,", c["tools"]["count"], "tools, benchmark", c["benchmark"].get("version"))'
    rm -rf "$PREV"
    echo "== done. Next: paste deploy/Caddyfile.v3.snippet into api.narrowhighway.com's route block and"
    echo "   add Environment=NH_VERIFY_URL=http://127.0.0.1:$PORT to nh-org.service; then: sudo systemctl reload caddy && sudo systemctl restart nh-org"
    exit 0
  fi
  sleep 1
done
echo "!! :$PORT never answered /health"; journalctl -u nh-v3 -n 20 --no-pager 2>/dev/null || true
rollback
