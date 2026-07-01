# quner

**Portable Linux efficiency daemon.** Install it once and it quietly keeps your
machine at its **work-per-joule optimum** — the same work, fewer joules —
adapting between *idle* and *heavy compute* automatically.

`quner` probes what levers your host exposes (CPU governor, Intel RAPL package
power, NVIDIA power-cap) and tunes the ones present to an **interior** operating
point — not max clock / max TDP — then holds it. Absent levers are reported, not
silently ignored. Everything is reversible; nothing destructive happens without
you asking for it.

```bash
pipx install quner
sudo quner install        # drops a root systemd service + re-tune timer
quner doctor              # what levers this host exposes
quner status              # current profile + operating point + energy
quner selftest            # transient, auto-reverting proof the levers work here
```

The efficiency principle derives from QIG experiment **EXP-132** (work-per-joule
peaks at an interior operating point); `quner` re-measures the optimum on *your*
hardware — no imported constants.

> Honest expectation: single-digit-to-~30% energy savings, workload-dependent.
> This is an efficiency tool (same work, fewer joules), never energy creation.

## Safety model

- **Reversible.** Every apply snapshots the prior governor / RAPL / GPU-cap to
  `/var/lib/quner/rollback.json`; `quner uninstall` and the service's stop hook
  restore it. `quner apply --restore` reverts on demand.
- **Fail-loud.** A lever the host doesn't expose is reported `unavailable`, never
  silently no-op'd. `quner doctor` shows exactly what's controllable.
- **Dry-run everywhere.** Every mutating command takes `--dry-run` (prints the
  exact writes, changes nothing).
- **Inspectable / testable.** All hardware paths are env-overridable
  (`QUNER_SYSFS_ROOT`, `QUNER_NVIDIA_SMI`, `QUNER_STATE_DIR`, …), so the real
  code runs against a fake tree with zero host impact — see `sandbox/run_sandbox.sh`.
- **reverse-PRIME is opt-in.** The one reboot-level change never fires on install
  or in the daemon; only via `quner prime enable` (dry-run first, reboot-gated,
  with a TTY recovery path).

## Validation ladder

1. **Sandbox** (`bash sandbox/run_sandbox.sh`) — proves ~all code with the real
   `/sys` byte-identical before/after. Safe to run anywhere.
2. **`quner selftest`** — transient, auto-reverting proof the levers move on
   *your* hardware (2-second governor flip, RAPL/GPU set-to-current, restore).
3. **`sudo quner install`** — hold the operating point continuously.

See `docs/design/` for the full design.
