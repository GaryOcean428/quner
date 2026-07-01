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

See `docs/design/` for the full design and safety model.
