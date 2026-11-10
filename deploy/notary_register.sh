#!/usr/bin/env bash
# Register, retire, list or verify notary stores on the box, exactly as the running service would see them.
#
#   sudo bash deploy/notary_register.sh register <store> <public_key>
#   sudo bash deploy/notary_register.sh retire <store>
#   sudo bash deploy/notary_register.sh list
#   sudo bash deploy/notary_register.sh verify <store> [--key <V3 public key>]
#
# What it does: refuses unless the nh-v3 unit is active; reads from the unit its service user (never root), its working
# directory, its interpreter (ExecStart's path), its code (PYTHONPATH), its data directory (CONCORDANCE_DATA_DIR) and its
# environment files; runs `python -m concordance notary ...` as that user, with that interpreter and that code, and with
# the unit's environment files (--env-file, read by the CLI itself, so the issuer key verify needs is never an argument
# and never printed), so the file's schema is always the one the served code reads; then reads the result back with
# `notary list` and prints it. Every command the CLI runs is one transaction, so a failed one changes nothing. It names no
# path of its own: everything comes from the unit.
#
# Exit 0 done; 1 the CLI refused (nothing was written); 2 a usage error from the CLI; 3 refused here, before anything
# ran (nothing was changed).
set -euo pipefail
UNIT="${UNIT:-nh-v3}"

die() { echo "!! $*; nothing was changed"; exit 3; }

[ "$#" -ge 1 ] || die "usage: $0 register <store> <public_key> | retire <store> | list | verify <store> [--key K]"
case "$1" in
  register|retire|list|verify) ;;
  *) die "unknown command '$1' (register, retire, list or verify)" ;;
esac

systemctl is-active --quiet "$UNIT" || die "$UNIT is not active"

prop() { systemctl show "$UNIT" -p "$1" --value; }
user="$(prop User)" || die "could not read $UNIT's User"
workdir="$(prop WorkingDirectory)" || die "could not read $UNIT's WorkingDirectory"
environment="$(prop Environment)" || die "could not read $UNIT's Environment"
exec_start="$(prop ExecStart)" || die "could not read $UNIT's ExecStart"
environment_files="$(prop EnvironmentFiles)" || die "could not read $UNIT's EnvironmentFiles"

data=""
code=""
set -f                                  # the unit's words are values, never patterns
for word in $environment; do
  case "$word" in
    CONCORDANCE_DATA_DIR=*) data="${word#CONCORDANCE_DATA_DIR=}" ;;
    PYTHONPATH=*) code="${word#PYTHONPATH=}" ;;
  esac
done
set +f
python="$(printf '%s\n' "$exec_start" | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n 1)"
# systemctl names each file as "<path> (ignore_errors=yes|no)". The CLI reads each one itself, as the service user, the
# way the unit loads it for the service, so a key in it (the issuer key, which verify needs) is never an argument and
# never printed. A missing file the unit may ignore is skipped.
env_files=()
while read -r f; do
  if [ -n "$f" ] && [ -f "$f" ]; then env_files+=(--env-file "$f"); fi
done < <(printf '%s\n' "$environment_files" | { grep -o '[^ ]* (ignore_errors=[a-z]*)' || true; } \
           | sed 's/ (ignore_errors=[a-z]*)$//')

[ -n "$user" ] || die "$UNIT names no service user"
[ "$user" != root ] || die "$UNIT runs as root; this script runs the CLI only as a service user"
[ -n "$workdir" ] && [ -d "$workdir" ] || die "$UNIT's working directory is not a directory: '$workdir'"
[ -n "$data" ] || die "$UNIT sets no CONCORDANCE_DATA_DIR"
[ -n "$code" ] || die "$UNIT sets no PYTHONPATH"
[ -n "$python" ] && [ -x "$python" ] || die "$UNIT's interpreter is not executable: '$python'"

cli() {
  ( cd "$workdir" && sudo -u "$user" env PYTHONPATH="$code" CONCORDANCE_DATA_DIR="$data" \
      "$python" -m concordance notary "$@" ${env_files[@]+"${env_files[@]}"} --data-dir "$data" )
}

echo "== $UNIT: as $user, with $python, code $code, data $data"
rc=0
cli "$@" || rc=$?
echo "== read back"
cli list || echo "!! the read-back failed"
exit "$rc"
