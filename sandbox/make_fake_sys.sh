#!/usr/bin/env bash
# Build a fake /sys tree for the quner Layer-A sandbox: N cpufreq cores + one
# intel-rapl package. quner writes here (QUNER_SYSFS_ROOT) instead of the host.
set -euo pipefail
ROOT="${1:?usage: make_fake_sys.sh <root>}"
NCORES="${2:-4}"

rm -rf "$ROOT"
for c in $(seq 0 $((NCORES - 1))); do
  d="$ROOT/devices/system/cpu/cpu$c/cpufreq"
  mkdir -p "$d"
  echo "performance powersave schedutil" > "$d/scaling_available_governors"
  echo "powersave" > "$d/scaling_governor"
done

rp="$ROOT/class/powercap/intel-rapl:0"
mkdir -p "$rp"
echo "1000000"       > "$rp/energy_uj"
echo "262143328850"  > "$rp/max_energy_range_uj"
echo "long_term"     > "$rp/constraint_0_name"
echo "85000000"      > "$rp/constraint_0_power_limit_uw"
echo "45000000"      > "$rp/constraint_0_max_power_uw"

echo "fake /sys built at $ROOT ($NCORES cores, 1 rapl package)"
