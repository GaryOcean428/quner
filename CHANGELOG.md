# Changelog

## 0.1.3 — 2026-07-01

Follow-up to fresh-machine feedback (cold-install VM + zero-lever host). The
`sudo quner install` → "command not found" gotcha (pipx installs to the user's
`~/.local/bin`, off root's PATH) is now addressed in the tool, not just the docs:

- **`quner install` drops a root-visible `/usr/local/bin/quner` launcher** (only
  if absent — never clobbers an existing binary), so plain `sudo quner …` works
  after the first install. `uninstall` removes it (only if it's ours).
- **README leads with the system-wide install** (`sudo pipx --global install
  quner`) that avoids the PATH issue entirely, and documents the precise
  requirement that `pipx ensurepath` needs a **login** shell (not just any new
  terminal / non-interactive ssh).
- Path is env-overridable (`QUNER_LAUNCHER_PATH`) and exercised in the sandbox.

Everything else in Parts 3–4 validated with **no bugs**: 3-tick profile
hysteresis (both directions, under real `stress-ng` load), turbostat-corroborated
RAPL telemetry, and fail-loud degradation on a zero-lever VM (doctor/selftest/
status/tune/daemon/timer — no crashes).

## 0.1.2 — 2026-07-01

Driven by fresh-machine feedback (Ubuntu 24.04 / NVIDIA T550). Confirmed bugs fixed:

- **Crash-restart baseline safety.** The daemon now captures the pristine
  pre-quner baseline **once** (`control.ensure_baseline()` at install / first
  boot) instead of re-snapshotting on every `serve()`. Previously a
  `Restart=on-failure` restart could snapshot an already-tuned host and lose the
  true baseline. `uninstall` clears the rollback file so a re-install re-captures.
- **systemd hardening.** The unit now runs with `NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome=read-only`, `ProtectControlGroups`,
  `ProtectKernelModules`, `ProtectKernelLogs`, `ProtectClock`, `RestrictRealtime`,
  `RestrictSUIDSGID`, `RestrictNamespaces`, `LockPersonality`, plus
  `StateDirectory`/`RuntimeDirectory`. `ProtectKernelTunables` is intentionally
  left off (it would block the sysfs governor/RAPL writes). Validated with
  `systemd-run` running `selftest` under the exact directives.
- **retune ↔ cache ↔ status connected.** New `quner retune` command re-tunes the
  *current* profile and **caches** the result (the timer now runs `retune`, not a
  bare `tune --apply` that never cached). `status.json` gains a `current` block
  reporting the **actual** hardware operating point (governor / GPU cap / RAPL),
  so it no longer reads as incomplete when a re-tune changed the GPU cap.
- **`tune --no-gpu`.** Restricts the sweep to CPU governors for CPU-only
  workloads, where the GPU-cap sweep otherwise measures GPU *idle*-power noise
  and can fake an "interior optimum". Documented in `tune --help`.
- **Honest EXP-132 wording.** The ±1.91% band is now described as a *fixed
  tie-break threshold imported from EXP-132*, not a per-host confidence interval.
- **memguard** never targets `zsh`/`fish`/`sh`/`dash`/`systemd-logind` (was
  `bash`-only), so a non-bash login shell can't be SIGTERM'd.
- **README** quickstart uses `sudo "$(which quner)" install` — a bare
  `sudo quner install` fails with `command not found` because pipx installs to
  the user's `~/.local/bin`, which isn't on root's PATH.

## 0.1.1 — 2026-07-01

- Honest `doctor` RAPL line when the energy counter is root-only
  (CVE-2020-8694): "intel-rapl present; energy counter is root-only" instead of a
  contradictory "available — not exposed".

## 0.1.0 — 2026-07-01

- Initial release: capability-detecting work-per-joule tuner (CPU governor /
  Intel RAPL PL1 / NVIDIA power-cap), workload profiles, memguard, reverse-PRIME
  (opt-in), systemd service + re-tune timer, safe-by-construction env seam.
