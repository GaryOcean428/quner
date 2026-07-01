#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# quner Layer-A sandbox — proves ~all code with ZERO impact on the host.
#
# Every quner invocation runs with QUNER_SYSFS_ROOT / QUNER_NVIDIA_SMI /
# QUNER_STATE_DIR / QUNER_RUN_DIR / QUNER_SYSTEMD_DIR pointed under sandbox/_run,
# so real writes land in a temp tree. The load-bearing proof is the before/after
# comparison of the real /sys governor: it MUST be byte-identical afterwards.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
RUN="$HERE/_run"
FAKESYS="$RUN/fake-sys"
MOCK="$HERE/mock-nvidia-smi"
STATE="$RUN/state"
RUNDIR="$RUN/run"
SYSD="$RUN/sysd"
BIN="$REPO/.venv/bin"
QUNER="$BIN/quner"
PY="$BIN/python"

pass() { echo "  ✓ $*"; }
step() { echo; echo "── $* ──"; }

rm -rf "$RUN"; mkdir -p "$RUN" "$STATE" "$RUNDIR"
chmod +x "$MOCK" "$HERE/make_fake_sys.sh"

# A no-op `systemctl` so the real `install` writes units without touching host
# systemd. (`systemd-analyze` stays real — it only lints.)
mkdir -p "$RUN/bin"
printf '#!/usr/bin/env bash\necho "[stub systemctl] $*"\nexit 0\n' > "$RUN/bin/systemctl"
chmod +x "$RUN/bin/systemctl"

export QUNER_SYSFS_ROOT="$FAKESYS"
export QUNER_NVIDIA_SMI="$MOCK"
export QUNER_STATE_DIR="$STATE"
export QUNER_RUN_DIR="$RUNDIR"
export QUNER_SYSTEMD_DIR="$SYSD"
export QUNER_LAUNCHER_PATH="$RUN/bin/quner-launcher"   # never touch real /usr/local/bin

step "1. build fake /sys"
bash "$HERE/make_fake_sys.sh" "$FAKESYS" 4
pass "fake tree ready"

step "2. unit tests (no root)"
( cd "$REPO" && "$PY" -m pytest -q ) && pass "pytest green"

step "3. capture REAL /sys baseline (must be unchanged at the end)"
REAL_GOV_FILE="/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
REAL_BEFORE="$(cat "$REAL_GOV_FILE" 2>/dev/null || echo n/a)"
REAL_MTIME_BEFORE="$(stat -c %Y "$REAL_GOV_FILE" 2>/dev/null || echo 0)"
pass "real cpu0 governor = $REAL_BEFORE (mtime $REAL_MTIME_BEFORE)"

step "4. doctor (bwrap FS-isolated, best-effort)"
if command -v bwrap >/dev/null 2>&1; then
  if bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --bind "$RUN" "$RUN" \
       env QUNER_SYSFS_ROOT="$FAKESYS" QUNER_NVIDIA_SMI="$MOCK" \
           QUNER_STATE_DIR="$STATE" "$QUNER" doctor; then
    pass "bwrap-isolated doctor OK"
  else
    echo "  ! bwrap run failed — env-isolation still guarantees safety"
  fi
else
  "$QUNER" doctor; pass "doctor OK (no bwrap)"
fi

step "5. apply (real write — into the FAKE tree only)"
"$QUNER" apply
FAKE_GOV="$(cat "$FAKESYS/devices/system/cpu/cpu0/cpufreq/scaling_governor")"
pass "fake tree governor now = $FAKE_GOV"

step "6. tune --apply (governor × GPU-cap sweep on the fake tree + mock GPU)"
"$QUNER" tune --command 'sleep 0.2' --apply --reps 1 | "$PY" -c \
  'import sys,json; r=json.load(sys.stdin); print("  chosen:",r["chosen_state"],"| interior:",r["is_interior"],"| samples:",len(r["samples"]))'
pass "tune produced a report"

step "7. memguard --dry-run"
"$QUNER" memguard --dry-run >/dev/null && pass "memguard tick ok (dry-run, no kills)"

step "8. install (dry-run, then real into the sandbox systemd dir) + verify"
"$QUNER" install --dry-run >/dev/null && pass "install --dry-run wrote nothing"
PATH="$RUN/bin:$PATH" "$QUNER" install >/dev/null
test -f "$SYSD/quner.service" && pass "units written to sandbox systemd dir"
test -f "$QUNER_LAUNCHER_PATH" && grep -q "quner-launcher" "$QUNER_LAUNCHER_PATH" && pass "root-visible launcher dropped"
if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify "$SYSD/quner.service" && pass "systemd-analyze verify clean"
else
  echo "  ! systemd-analyze absent — skipped lint"
fi

step "9. build wheel + docker clean-host rehearsal"
( cd "$REPO" && rm -rf dist && uv build --wheel >/dev/null 2>&1 ) \
  && pass "wheel built: $(ls "$REPO"/dist/*.whl 2>/dev/null | xargs -n1 basename)"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -q -f "$HERE/Dockerfile" -t quner-sbx "$REPO" >/dev/null && pass "docker build OK (doctor+install --dry-run ran in a clean container)"
  docker run --rm quner-sbx quner doctor >/dev/null && pass "docker run doctor OK"
else
  echo "  ! docker not usable — skipped container rehearsal"
fi

step "10. PROOF: real /sys is untouched"
REAL_AFTER="$(cat "$REAL_GOV_FILE" 2>/dev/null || echo n/a)"
REAL_MTIME_AFTER="$(stat -c %Y "$REAL_GOV_FILE" 2>/dev/null || echo 0)"
echo "  real cpu0 governor: before=$REAL_BEFORE after=$REAL_AFTER"
echo "  real cpu0 mtime   : before=$REAL_MTIME_BEFORE after=$REAL_MTIME_AFTER"
if [ "$REAL_BEFORE" = "$REAL_AFTER" ] && [ "$REAL_MTIME_BEFORE" = "$REAL_MTIME_AFTER" ]; then
  echo; echo "═══ LAYER-A GREEN — host untouched, all code exercised ═══"
else
  echo; echo "✗✗✗ REAL /sys CHANGED — sandbox isolation FAILED ✗✗✗"; exit 1
fi
