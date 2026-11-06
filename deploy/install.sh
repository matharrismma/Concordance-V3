#!/usr/bin/env bash
# Install or update Concordance V3 on the box. Idempotent. Run AS nh (or: sudo -u nh bash deploy/install.sh).
#
#   curl -fsSL https://raw.githubusercontent.com/matharrismma/Concordance-V3/main/deploy/install.sh | bash
#   # or, from a checkout:  bash deploy/install.sh
#
# What it does: clone/pull /home/nh/concordance-3 at the tag or branch in $REF (default: main), build the venv, run the
# gates (suite + benchmark --check + schema --check), install nh-v3.service, restart, health-check on :8020, then hold
# past WatchdogSec. Any failure on the way puts the previous commit and unit back in place and restarts.
set -euo pipefail
REF="${REF:-main}"
DEST="${DEST:-/home/nh/concordance-3}"
REPO="${REPO:-https://github.com/matharrismma/Concordance-V3}"
PORT="${PORT:-8020}"
UNIT="${UNIT_DIR:-/etc/systemd/system}/nh-v3.service"
RECORD="$DEST.ship"             # what this ship replaced: a sha, a unit and one generated file, beside the checkout
BENCHMARK="data/benchmark_last.json"
HOLD_PAST_S=15                  # how far past WatchdogSec the service must hold before the record goes
service_restarted=0

# Nothing here moves or deletes a seal or .env, on any exit. Seals are ignored by git and .env is not tracked, so neither
# a checkout nor a forced one can reach them, and this script names neither. Of the files git tracks under data/, the
# only one anything writes is $BENCHMARK, and that writer is the last gate below, not the runtime. A checkout would
# refuse to pass it, and a forced one would drop it, so its bytes are in the record and go back by a rename.

can_sudo() { { command -v sudo >/dev/null && [ -w "$(dirname "$UNIT")" ]; } || sudo -n true 2>/dev/null; }

answers() {
  local i
  for i in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

put_benchmark_back() {
  if [ -f "$RECORD/benchmark_last.json" ]; then
    cp -p "$RECORD/benchmark_last.json" "$RECORD/benchmark.back" && mv "$RECORD/benchmark.back" "$DEST/$BENCHMARK"
  fi
}

# Every way out that did not finish comes here, the set -e exits among them (the EXIT trap below): the previous commit in
# place, the saved unit, a reinstall if the dependencies moved, a restart, and a read of /health that it reports. Exit 1
# when all of that worked; exit 3 when any of it did not, with the record kept, so a later run still knows what to restore.
rollback() {
  set +e
  trap - EXIT
  local code=1 was="" failed=""
  echo "!! failed — putting back the previous commit and unit"
  if [ -f "$RECORD/sha" ]; then
    was="$(cat "$RECORD/sha")"
    failed="$(git -C "$DEST" rev-parse HEAD)"
    if git -C "$DEST" checkout -q --force "$was"; then
      put_benchmark_back || { echo "!! could not put $BENCHMARK back; a human must look"; code=3; }
      if ! git -C "$DEST" diff --quiet "$failed" "$was" -- pyproject.toml; then
        ( cd "$DEST" && .venv/bin/pip install -q -e ".[math,scribe,signing,dev]" ) || { echo "!! the reinstall failed; a human must look"; code=3; }
      fi
    else
      echo "!! could not check out $was; a human must look"
      code=3
    fi
  fi
  if can_sudo; then
    if [ -f "$RECORD/nh-v3.service" ]; then
      sudo cp "$RECORD/nh-v3.service" "$UNIT" || { echo "!! could not put the unit back; a human must look"; code=3; }
    elif [ -f "$UNIT" ]; then
      sudo systemctl disable nh-v3
      sudo rm -f "$UNIT" || { echo "!! could not take the new unit away; a human must look"; code=3; }
    fi
    sudo systemctl daemon-reload || { echo "!! daemon-reload failed; a human must look"; code=3; }
    if [ -f "$UNIT" ]; then
      if ! sudo systemctl restart nh-v3; then
        echo "!! the service did not restart; a human must look"
        code=3
      elif ! answers; then
        echo "!! the service restarted, and /health does not answer; a human must look"
        code=3
      elif [ "$code" = 1 ]; then
        echo "== rolled back to ${was:-the previous state}: /health answers"
      else
        echo "   the service restarted and /health answers, on whatever the failure above left in place"
      fi
    fi
  fi
  if [ "$code" = 1 ]; then rm -rf "$RECORD"; fi
  exit "$code"
}

echo "== Concordance V3 install ($REF -> $DEST)"
if [ -d "$DEST/.git" ]; then
  changed="$(git -C "$DEST" status --porcelain --untracked-files=no -- data | grep -v " $BENCHMARK\$" || true)"
  if [ -n "$changed" ]; then
    echo "!! tracked files under data/ differ from their commit, and a rollback would overwrite them; nothing was changed"
    echo "$changed"
    echo "   a human must look"
    exit 3
  fi
fi
# A record with a sha is a run that did not finish: what it replaced is still what a rollback must go back to.
if [ -f "$RECORD/sha" ]; then
  echo "== an earlier run did not finish: keeping what it recorded"
else
  rm -rf "$RECORD" "$RECORD.new"
  mkdir "$RECORD.new"
  if [ -d "$DEST/.git" ]; then
    git -C "$DEST" rev-parse HEAD > "$RECORD.new/sha"
    [ ! -f "$DEST/$BENCHMARK" ] || cp -p "$DEST/$BENCHMARK" "$RECORD.new/benchmark_last.json"
  fi
  [ ! -f "$UNIT" ] || cp "$UNIT" "$RECORD.new/nh-v3.service"
  mv "$RECORD.new" "$RECORD"
fi
trap rollback EXIT

if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch -q origin
  git -C "$DEST" checkout -q -- "$BENCHMARK"      # the last ship rewrote it, which would block the checkout
  git -C "$DEST" checkout -q "$REF"
  git -C "$DEST" pull -q --ff-only origin "$REF" 2>/dev/null || true
  put_benchmark_back
else
  git clone -q --branch "$REF" "$REPO" "$DEST"
fi
cd "$DEST"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[math,scribe,signing,dev]"

echo "== gates"
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider >/tmp/nh-v3-pytest.log 2>&1 || { tail -5 /tmp/nh-v3-pytest.log; rollback; }
PYTHONPATH=src .venv/bin/python tools/benchmark.py --check || rollback
PYTHONPATH=src .venv/bin/python tools/schema_gen.py --check || rollback
PYTHONPATH=src .venv/bin/python tools/benchmark.py --json > "$RECORD/benchmark.new" || rollback
mv "$RECORD/benchmark.new" "$BENCHMARK"           # only a finished run replaces it, and all at once

echo "== service"
if can_sudo; then
  sudo cp deploy/nh-v3.service "$UNIT"
  sudo systemctl daemon-reload
  sudo systemctl enable --now nh-v3
  sudo systemctl restart nh-v3
  service_restarted=1
else
  echo "   (no sudo: copy deploy/nh-v3.service to /etc/systemd/system and enable it yourself)"
fi

echo "== health"
if ! answers; then
  echo "!! :$PORT never answered /health"; journalctl -u nh-v3 -n 20 --no-pager 2>/dev/null || true
  rollback
fi
curl -fsS "http://127.0.0.1:$PORT/capabilities" | .venv/bin/python -c 'import json,sys; c=json.load(sys.stdin); print("   up:", c["verifiers"]["modules"], "verifier modules,", c["tools"]["count"], "tools, benchmark", c["benchmark"].get("version"))'

# A service can answer /health and still fail its watchdog, and then it dies a full WatchdogSec later. So the record stays
# until the service has held past that as the same process, with no restart. HOLD_S overrides, for a dry run.
if [ "$service_restarted" = 1 ]; then
  watchdog_s="$(sed -n 's/^WatchdogSec=\([0-9]*\).*/\1/p' deploy/nh-v3.service | head -n 1)"
  hold_s="${HOLD_S:-$(( ${watchdog_s:-0} + HOLD_PAST_S ))}"
  pid="$(systemctl show nh-v3 -p MainPID --value)"
  restarts="$(systemctl show nh-v3 -p NRestarts --value)"
  echo "== hold ${hold_s}s (MainPID $pid, NRestarts $restarts)"
  if [ "${pid:-0}" = 0 ]; then echo "!! nh-v3 has no main process"; rollback; fi
  held=0
  while [ "$held" -lt "$hold_s" ]; do
    sleep 5
    held=$(( held + 5 ))
    if [ "$(systemctl show nh-v3 -p MainPID --value)" != "$pid" ] || [ "$(systemctl show nh-v3 -p NRestarts --value)" != "$restarts" ]; then
      echo "!! nh-v3 did not hold: MainPID or NRestarts changed by ${held}s"; journalctl -u nh-v3 -n 20 --no-pager 2>/dev/null || true
      rollback
    fi
  done
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || { echo "!! :$PORT stopped answering /health during the hold"; rollback; }
fi

trap - EXIT
rm -rf "$RECORD"
echo "== done. Next: paste deploy/Caddyfile.v3.snippet into api.narrowhighway.com's route block and"
echo "   add Environment=NH_VERIFY_URL=http://127.0.0.1:$PORT to nh-org.service; then: sudo systemctl reload caddy && sudo systemctl restart nh-org"
if ! grep -q CONCORDANCE_ISSUER_KEY .env 2>/dev/null; then
  echo "   receipts are self-attested until you add an issuer key: .venv/bin/python -m concordance keygen >> .env && chmod 600 .env && echo CONCORDANCE_PUBLISH=1 >> .env && sudo systemctl restart nh-v3"
fi
