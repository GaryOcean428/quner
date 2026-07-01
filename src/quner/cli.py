"""quner command-line interface.

    quner doctor                 what levers this host exposes (fail-loud)
    quner status                 telemetry + the EXP-132 principle
    quner apply [--restore]      apply the current profile's operating point
    quner profile <name>         apply a named profile (idle|training)
    quner tune [--command C]     profile work/joule, find the interior optimum
    quner install | uninstall    systemd service + re-tune timer
    quner prime {status,enable,disable}   reverse-PRIME (opt-in)
    quner memguard               one OOM-watchdog tick
    quner selftest               transient, auto-reverting proof the levers work
    quner serve                  run the daemon loop (used by systemd)

Every mutating command takes ``--dry-run`` (prints, changes nothing).
"""

from __future__ import annotations

import argparse
import json
import sys

from quner import __version__


def _print(obj) -> None:
    print(json.dumps(obj, indent=2) if isinstance(obj, (dict, list)) else obj)


# ── command handlers ──────────────────────────────────────────────────────────

def _cmd_doctor(_args) -> int:
    from quner import detect
    print("quner doctor — capability report")
    for line in detect.doctor_lines():
        print("  " + line)
    return 0


def _cmd_status(_args) -> int:
    from quner import tune
    _print(tune.status())
    return 0


def _cmd_apply(args) -> int:
    from quner import control, detect, profiles, tune
    if args.restore:
        _print({"restored": control.restore()})
        return 0
    profile = profiles.Detector(ticks=1).update()
    target = (profiles.cache_get(detect.host_fingerprint(), profile)
              or profiles.default_state_for(profile))
    if args.dry_run:
        print(f"[dry-run] profile={profile} target={target.label()} — nothing applied")
        return 0
    _print({"profile": profile, "target": target.label(),
            "applied": tune.apply_state(target)})
    return 0


def _cmd_profile(args) -> int:
    from quner import profiles, tune
    target = profiles.default_state_for(args.name)
    if args.dry_run:
        print(f"[dry-run] profile={args.name} target={target.label()} — nothing applied")
        return 0
    _print({"profile": args.name, "target": target.label(),
            "applied": tune.apply_state(target)})
    return 0


def _cmd_tune(args) -> int:
    from quner import tune
    run = tune.command_runner(args.command) if args.command \
        else tune.command_runner("sleep 0.1")
    rep = tune.tune(run, apply=args.apply, reps=args.reps)
    _print(rep.as_dict())
    return 0


def _cmd_install(args) -> int:
    from quner import service
    service.install(dry_run=args.dry_run, interval=args.interval)
    return 0


def _cmd_uninstall(args) -> int:
    from quner import service
    service.uninstall(dry_run=args.dry_run)
    return 0


def _cmd_prime(args) -> int:
    from quner import prime
    if args.prime_cmd == "status":
        _print(prime.status())
    elif args.prime_cmd == "enable":
        _print(prime.enable(dry_run=args.dry_run))
    elif args.prime_cmd == "disable":
        _print(prime.disable(dry_run=args.dry_run))
    else:
        print("usage: quner prime {status,enable,disable}")
        return 2
    return 0


def _cmd_memguard(args) -> int:
    from quner import memguard
    _print(memguard.tick(dry_run=args.dry_run))
    return 0


def _cmd_serve(args) -> int:
    from quner import daemon
    daemon.serve(interval=args.interval, dry_run=args.dry_run,
                 memguard_on=args.memguard)
    return 0


def _cmd_selftest(_args) -> int:
    """Transient, auto-reverting proof each present lever moves on THIS host.
    Snapshots state, nudges each lever to a benign value, verifies, restores."""
    from quner import control
    from quner import telemetry as t

    snap = control.snapshot(persist=False)
    results: dict[str, str] = {}

    # governor: flip to another available governor, then back
    govs = t.available_governors()
    cur = t.current_governor()
    if govs and cur:
        alt = next((g for g in govs if g != cur), None)
        if alt:
            ok = t.set_governor(alt)
            restored = t.set_governor(cur)
            results["governor"] = ("PASS" if ok and restored and t.current_governor() == cur
                                   else "FAIL")
        else:
            results["governor"] = "skip (only one governor offered)"
    else:
        results["governor"] = "unavailable"

    # rapl: write current PL1 back to itself (no net change, exercises the write)
    cur_uw = control.read_rapl_pl1_uw()
    results["rapl"] = ("PASS" if cur_uw and control._write_rapl_uw(cur_uw)
                       else ("unavailable" if not cur_uw else "FAIL"))

    # gpu cap: set to its own max (= default/uncap; benign no-op change)
    rng = t.gpu_power_limit_range_w()
    if rng:
        results["gpu_cap"] = "PASS" if t.set_gpu_power_limit_w(rng[1]) else "FAIL"
    else:
        results["gpu_cap"] = "unavailable"

    control.restore(snap)  # belt-and-suspenders full restore
    print("quner selftest — transient, auto-reverted")
    for lever, verdict in results.items():
        print(f"  {lever:>10}: {verdict}")
    failed = [k for k, v in results.items() if v == "FAIL"]
    return 1 if failed else 0


# ── parser ────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quner", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", "-V", action="version", version=f"quner {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="what levers this host exposes").set_defaults(func=_cmd_doctor)
    sub.add_parser("status", help="telemetry + principle").set_defaults(func=_cmd_status)

    ap = sub.add_parser("apply", help="apply the current profile's operating point")
    ap.add_argument("--restore", action="store_true", help="restore the saved baseline")
    ap.add_argument("--dry-run", action="store_true")
    ap.set_defaults(func=_cmd_apply)

    pr = sub.add_parser("profile", help="apply a named profile")
    pr.add_argument("name", choices=["idle", "training"])
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=_cmd_profile)

    tu = sub.add_parser("tune", help="find the interior work/joule optimum")
    tu.add_argument("--command", help="workload command to profile")
    tu.add_argument("--apply", action="store_true", help="apply + hold the chosen state")
    tu.add_argument("--reps", type=int, default=3)
    tu.set_defaults(func=_cmd_tune)

    ins = sub.add_parser("install", help="install the systemd service + timer")
    ins.add_argument("--dry-run", action="store_true")
    ins.add_argument("--interval", default="30min", help="re-tune timer interval")
    ins.set_defaults(func=_cmd_install)

    uni = sub.add_parser("uninstall", help="remove the service + restore baseline")
    uni.add_argument("--dry-run", action="store_true")
    uni.set_defaults(func=_cmd_uninstall)

    pm = sub.add_parser("prime", help="reverse-PRIME (opt-in)")
    pm.add_argument("prime_cmd", choices=["status", "enable", "disable"])
    pm.add_argument("--dry-run", action="store_true")
    pm.set_defaults(func=_cmd_prime)

    mg = sub.add_parser("memguard", help="one OOM-watchdog tick")
    mg.add_argument("--dry-run", action="store_true")
    mg.set_defaults(func=_cmd_memguard)

    sv = sub.add_parser("serve", help="run the daemon loop (systemd)")
    sv.add_argument("--interval", type=float, default=10.0)
    sv.add_argument("--dry-run", action="store_true")
    sv.add_argument("--memguard", action="store_true")
    sv.set_defaults(func=_cmd_serve)

    sub.add_parser("selftest", help="transient, auto-reverting lever proof").set_defaults(func=_cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)
