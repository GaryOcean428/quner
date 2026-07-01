# quner — portable Linux efficiency daemon — design

Date: 2026-07-01
Author: CC2
Status: approved (design) → implementation

## 1. Purpose

A single command you install once that then quietly keeps the machine at its
**work-per-joule optimum** — the same work, fewer joules — adapting between
*idle* and *heavy compute* (training) automatically. Installable and generally
available (PyPI as `quner`), portable across Linux hosts, safe by construction.

The efficiency claim is grounded in **EXP-132** (qig-verification): total-system
work-per-joule peaks at an *interior* operating point, not at max clock / max
TDP. `quner` treats that as a calibration prior and **re-measures the optimum on
each host** (the lattice `h≈1.5` constant does not transfer — only the *shape* of
the law and the confidence-band methodology do).

### Non-goals
- Not energy creation. Honest expectation: single-digit-to-~30% savings,
  workload-dependent; memory-bound jobs benefit least, GPU/compute-bound most.
- Not an overclocking / undervolting tool. Only kernel/driver-sanctioned knobs.
- Not a GUI. CLI + systemd only in v1.
- No QIG/LLM/physics runtime dependency (see §4).

## 2. Target & portability

Runs on **any Linux host**; the Dell G5 5500 (i7-10750H, GTX 1650 Ti, Intel UHD,
Ubuntu 26.04) is only the reference host. `quner` **probes what levers exist** and
tunes the present ones; absent levers are reported, never silently no-op'd
(**fail-loud**, per the no-silent-stubs discipline).

Levers, each independently optional:
- **CPU governor** — `cpufreq` `scaling_governor` (write needs root).
- **CPU package power (RAPL PL1)** — `intel-rapl:N/constraint_0_power_limit_uw`
  (write needs root). *Net-new writer* — the ported code only reads RAPL.
- **NVIDIA power-cap** — `nvidia-smi -pl` clamped to the driver's [min,max].
- **Display topology (reverse-PRIME)** — iGPU drives the display so the dGPU is
  free for compute (opt-in only; §9).

On a host missing a lever (VM, no NVIDIA driver, AMD, locked-down), the
corresponding reader returns `None` and `quner doctor` prints e.g.
`nvidia -pl: unavailable (no nvidia-smi)` — and the daemon tunes the rest.

## 3. Architecture

`quner` — a `pip`/`pipx`-installable package: a CLI + a **root systemd system
service + re-tune timer**. Modules (each a single, testable responsibility):

| Module | Responsibility |
|---|---|
| `quner.telemetry` | Read energy (RAPL wrap-aware, GPU power) + list/read operating states. Ported from qig-applied `efficiency/telemetry.py`, with the `QUNER_SYSFS_ROOT` seam (§6) and GPU helpers vendored (no qig-applied import). |
| `quner.control` | Apply the privileged levers: `set_governor`, `set_gpu_power_limit_w`, **net-new `set_rapl_pl1_w`**. Every apply snapshots prior state for rollback. |
| `quner.tune` | The work/joule optimiser: sweep governor × GPU-cap (× RAPL) states, locate the interior optimum + ±1.91% band. Ported from `efficiency/daemon.py`. |
| `quner.detect` | Capability detection → the `doctor` report; host fingerprint used to key the per-host cache. |
| `quner.profiles` | Workload detection (`nvidia-smi` GPU-util + `loadavg` → `idle`\|`training`) with **hysteresis**; profile→operating-point map; per-(host,profile) `best_state` cache. |
| `quner.prime` | reverse-PRIME enable/disable/status — opt-in, dry-run-first, backup+rollback, reboot-gated (§9). |
| `quner.memguard` | earlyoom-style watchdog: warn then SIGTERM the largest offender before a kernel OOM lock (§10). |
| `quner.daemon` | The service loop: detect profile → apply cached best_state → memguard tick → write `status.json`. Runs a full re-tune when the timer fires or on first-seen profile. |
| `quner.service` | Generate + install/uninstall the systemd unit + timer; `--dry-run` prints unit text; `systemd-analyze verify` lints. |
| `quner.cli` | `quner install|uninstall|status|doctor|apply|profile|tune|selftest|prime|memguard`. |
| `quner.calibration` | EXP-132 info/joule curve + interior-optimum principle string, as an internal calibration table (the only physics-derived content). |

## 4. Reused foundation & the standalone/DRY decision

The proven primitives already exist in **qig-applied** and are ported verbatim
(then extended), so `quner` ships correct code from day one:

- `qig_applied/efficiency/telemetry.py` → RAPL wrap-aware reader, cpufreq
  read/write with the **double-allowlist** (`_KNOWN_GOVERNORS` ∩ live
  `available_governors()`), `EnergySampler`, `telemetry_status()`.
- `qig_applied/efficiency/daemon.py` → `OperatingState`, `apply_state`,
  `profile_state`, `tune()` (interior test + band cert + honest diagnostics),
  `command_runner`.
- `qig_applied/inference/accelerate.py` → GPU helpers `set_power_limit_w`
  (clamped, `sudo -n` fallback), `power_limit_range_w`, `read_power_w`,
  `PowerSampler`. **Vendored** into `quner.telemetry` so `quner` has **zero**
  qig-applied import (a sellable product must not drag in the physics monorepo).

**Decision: Approach A (standalone, self-contained).** `quner` is the new
canonical home for these generic systems primitives. This *temporarily*
duplicates them in qig-applied. That duplication is **raised, not hidden**
(single-source-of-truth rule): the follow-up (Approach C) inverts the
dependency — qig-applied `efficiency/` and qig-studio `optim_launch.py` import
`quner` — and is **coordinated with CC1** because it touches the prelaunch seam
CC1 owns. Not in v1.

## 5. Data flow

**Service loop** (root `quner.service`), every `tick` (default 10 s):
1. `profiles.detect()` → `idle` | `training` (hysteresis: N consecutive ticks
   before switching, so it doesn't flap on a transient spike).
2. If profile changed **or** no cached `best_state` for it → apply the cached
   `best_state`; if none cached, apply the profile's *conservative default*
   (idle→powersave/low-cap; training→performance/full-cap) and mark the profile
   as "needs tune".
3. `memguard.tick()`.
4. Write `/run/quner/status.json` (profile, applied state, energy sample,
   lever availability, last-tune time).

**Re-tune timer** (`quner-retune.timer`, default every 30 min *while idle*):
runs `tune.tune(work_fn, apply=True)` for the **current** profile and updates
its cache entry. Crucially, the re-tune **never runs while `training` is the
active profile** — this is how coordination seam #4 is honoured (§16): quner
detects CC1's run and does *not* perturb the GPU with an exploratory sweep.

The daemon loop only *applies* cached states (cheap, non-perturbing). Only the
timer *explores* (a real sweep), and only when idle.

## 6. Privilege & safety

- **Root systemd system service.** All privileged writes go through
  `quner.control`, which enforces the allowlist/clamp before every write.
- **Snapshot + rollback.** Before the first apply, current governor / RAPL PL1 /
  GPU cap are saved to `/var/lib/quner/rollback.json`. `quner uninstall` and
  `quner apply --restore` return the host to those values. The service also
  restores on stop (`ExecStop`).
- **`QUNER_SYSFS_ROOT` test seam.** All sysfs paths are built from
  `os.environ.get("QUNER_SYSFS_ROOT", "/sys")`. Pointed at a temp tree, the
  *real* write code executes against a fake `/sys` — zero host impact. Likewise
  `QUNER_NVIDIA_SMI` overrides the `nvidia-smi` binary with a mock. This is the
  backbone of Layer-A validation (§11) and the unit tests.
- **`--dry-run`** on every mutating command prints the exact writes/commands
  without executing them.
- **fail-loud**: absent lever → explicit "unavailable" in `doctor`/`status`,
  never a silent success.

## 7. EXP-132 calibration (the one physics tie)

`quner.calibration` holds the info/joule curve (peak **0.808 at h=1.5**, band
`[0.793, 0.824]`, ±1.91% invariant band) and the principle string. Its role:
the tuner's objective is `work_per_joule` (the interior optimum), **not**
`work_per_s` (throughput endpoint). Per-host absolute values are always
re-measured; the curve is a prior on *shape*, and the ±1.91% band is the
certification threshold (an optimum only counts if it stands out of the band).
This is the **only** QIG-derived content; everything else is ordinary systems
engineering (no Fisher-Rao / purity constraints — per the segmentation note).

## 8. Workload detection & profiles

- **Signal:** `nvidia-smi --query-gpu=utilization.gpu` (if present) OR sustained
  `loadavg`/CPU-util (fallback when no GPU). Threshold: GPU-util > 30% or
  1-min load > `0.6 × nproc` → `training`, else `idle`.
- **Hysteresis:** require 3 consecutive ticks agreeing before switching.
- **Profiles:** `idle` (favor quiet/cool: powersave, RAPL low, GPU capped) and
  `training` (favor throughput-at-efficiency: the tuned interior optimum, GPU at
  or near full cap). A `manual` override exists via `quner profile <name>`.

## 9. reverse-PRIME (opt-in only)

`quner prime status|enable|disable`. Makes the iGPU the primary display sink so
the dGPU (and its full power/VRAM) is dedicated to compute. Guardrails:
- **Never on install**; only via explicit `quner prime enable`.
- **Dry-run first** (prints the exact GDM/Wayland/Xorg changes).
- **Backup** the current display config; `quner prime disable` restores it.
- **Reboot-gated** with a printed recovery path (how to revert from a TTY if the
  display fails to come up).
- **No-op with reason** where reverse-PRIME is meaningless (no NVIDIA driver →
  already iGPU-only).

## 10. memguard

`quner.memguard` — earlyoom-style watchdog inside the daemon loop: when
`MemAvailable` drops below a threshold (default 8% / configurable), warn; below a
harder floor (default 4%), SIGTERM the highest-RSS non-critical process (never
PID 1, never the daemon, never sshd) to keep a runaway training run from
hard-locking the box. Disabled by default; enabled by config/flag.

## 11. Validation ladder (primary machine never risked without explicit go)

- **Layer A — sandbox here, zero host impact.** `QUNER_SYSFS_ROOT=/tmp/quner-sbx`
  (real write code → fake `/sys`) + `QUNER_NVIDIA_SMI` mock + `bwrap` isolation +
  a throwaway **docker** container for the install/uninstall rehearsal +
  `systemd-analyze verify` on generated units. Proves ~all code; cannot touch
  real settings. `sandbox/run_sandbox.sh` orchestrates it.
- **Layer B — `quner selftest`, opt-in, on the real host.** Transient +
  auto-reverting: snapshot → 2 s governor flip / RAPL-to-current / cap-to-current
  → verify the write landed → **restore**. Proves the levers move *this* silicon.
  Excludes reverse-PRIME. Only on explicit go.
- **Layer C — reverse-PRIME, deferred** until a spare host is available or the
  user explicitly chooses.

## 12. Testing strategy

- Unit tests run with `QUNER_SYSFS_ROOT` → a fixture tree and `QUNER_NVIDIA_SMI`
  → a mock script; **no root needed in CI**.
- Cover: allowlist rejection (bad governor never written), RAPL wrap correction,
  clamp on GPU cap, rollback round-trip, capability-detect on a lever-less tree
  (all `unavailable`), profile hysteresis, tune interior/band logic, unit-file
  generation lints clean.
- Every mutating CLI path has a `--dry-run` asserted to write nothing.

## 13. Packaging & publish

- `pyproject.toml`, src-layout, `[project.scripts] quner = "quner.cli:main"`.
  Stdlib-only core (optional `nvidia-ml-py` extra for pynvml; nvidia-smi
  subprocess is the fallback). Python ≥ 3.10.
- Build with `uv build`; validate Layer A; **then** publish to PyPI as `quner`
  using `PYPI_TOKEN` from `qig-verification/.env`. TestPyPI dry-run first.
- Name `quner` is provisional-until-publish (rename is cheap before reserving).

## 14. Coordination seams (CC1)

- **#2 prelaunch (`qig-studio/optim_launch.py`)** — untouched in v1. The
  invert-dependency follow-up waits for CC1's run lease.
- **#4 GPU power-cap during a run** — solved by design: quner detects the
  training workload and *applies a cached profile*, deferring all exploratory
  sweeps to idle. It never sweeps mid-run.

## 15. Open follow-ups (registered, not in v1)

- Approach C: invert qig-applied/qig-studio to import `quner` (with CC1).
- AMD GPU power-cap lever; `amd_pstate` governor nuances.
- Optional cross-machine job distribution (unrelated to the daemon).

## 16. Success criteria (v1)

1. `quner doctor` correctly reports every lever's availability on the reference
   host and on a lever-less tree (fail-loud).
2. Layer-A sandbox run is green end-to-end with **zero** writes outside
   `QUNER_SYSFS_ROOT` / the docker container (proven by an untouched real `/sys`).
3. Unit tests green without root.
4. `quner install` generates a unit that passes `systemd-analyze verify`;
   `uninstall` fully reverts.
5. Published to PyPI as `quner`, `pipx install quner` works, only after 1–4.
