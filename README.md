# quner

**Portable Linux efficiency daemon.** Install it once and it quietly keeps your
machine at its **work-per-joule optimum** — the same work, fewer joules —
adapting between *idle* and *heavy compute* automatically.

`quner` probes what levers your host exposes (CPU governor, Intel RAPL package
power, NVIDIA power-cap) and tunes the ones present to an **interior** operating
point — not max clock / max TDP — then holds it. Absent levers are reported, not
silently ignored. Everything is reversible; nothing destructive happens without
you asking for it.

**Recommended — install system-wide so `root`/`sudo` finds it directly:**

```bash
sudo pipx --global install quner     # or: sudo pip install quner
sudo quner install                    # just works — drops the service + timer
quner doctor                          # what levers this host exposes
sudo quner selftest                   # transient, auto-reverting proof
```

**Alternative — per-user pipx install:**

```bash
pipx install quner
quner doctor
sudo "$(which quner)" install         # see note below
```

> **Why `sudo "$(which quner)"` for a per-user install?** `pipx` puts the binary
> in your **user** `~/.local/bin`, which isn't on `root`'s `PATH` — so a bare
> `sudo quner` gives `command not found`. `sudo "$(which quner)"` (or
> `sudo env "PATH=$PATH" quner …`) runs the binary you installed. **After that
> first install, quner drops a `/usr/local/bin/quner` launcher**, so plain
> `sudo quner …` works from then on (`uninstall` removes it).
>
> **PATH note:** `pipx ensurepath` appends to `~/.bashrc`, which only a **login**
> shell sources — open a new *login* shell / re-login (a plain terminal tab or a
> non-interactive `ssh host 'cmd'` may not pick it up). The system-wide install
> above avoids this entirely.

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
