"""The daemon service loop.

Each tick: detect the workload profile → apply the cached (or default) operating
point for it → run a memguard tick → publish ``status.json``. The loop only
*applies* cheap cached states; the expensive *exploratory* re-tune runs
separately (the systemd timer, or ``quner tune``) and is REFUSED while the
profile is ``training`` — so quner never perturbs an active run with a power
sweep (coordination seam #4).

Paths are env-overridable (``QUNER_RUN_DIR`` for status.json), so the whole loop
runs in the sandbox with zero host impact.
"""

from __future__ import annotations

import json
import os
import signal
import time

from quner import control, detect, memguard, profiles, tune
from quner import telemetry as t


def RUN_DIR() -> str:
    return os.environ.get("QUNER_RUN_DIR", "/run/quner")


def _current_operating_point() -> dict:
    """Ground-truth read-back of what is ACTUALLY set on the hardware right now
    (may differ from this loop's own decision if the re-tune timer changed it)."""
    return {
        "governor": t.current_governor(),
        "gpu_cap_w": t.read_gpu_power_limit_w(),
        "rapl_pl1_uw": control.read_rapl_pl1_uw(),
    }


def write_status(status: dict) -> str:
    d = RUN_DIR()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "status.json")
    with open(path, "w") as fh:
        json.dump(status, fh, indent=2)
    return path


def run_once(detector: profiles.Detector, *, dry_run: bool = False,
             memguard_on: bool = False) -> dict:
    """One daemon tick. Applies the cached/default state for the current
    profile (unless dry_run) and writes status.json."""
    profile = detector.update()
    fp = detect.host_fingerprint()
    target = profiles.cache_get(fp, profile) or profiles.default_state_for(profile)
    applied = {} if dry_run else tune.apply_state(target)
    mg = memguard.tick(dry_run=dry_run) if memguard_on else {"action": "disabled"}
    status = {
        "profile": profile,
        "target_state": target.label(),
        "applied": applied,
        "current": _current_operating_point(),   # actual hardware state right now
        "memguard": mg,
        "dry_run": dry_run,
        "capabilities": {k: v["available"] for k, v in detect.capabilities().items()},
    }
    write_status(status)
    return status


def retune(profile: str, work_fn=None):
    """Exploratory re-tune for a profile → cache the chosen state. REFUSED while
    ``training`` (never sweep power mid-run). Returns the TuneReport, or None if
    refused."""
    if profile == profiles.TRAINING:
        return None
    run = work_fn or tune.command_runner("sleep 0.05", work_units=1.0)
    rep = tune.tune(run, apply=True)
    if rep.chosen_state is not None:
        profiles.cache_put(detect.host_fingerprint(), profile, rep.chosen_state)
    return rep


def serve(interval: float = 10.0, dry_run: bool = False,
          memguard_on: bool = False) -> None:
    """The service loop: snapshot baseline, tick until SIGTERM/SIGINT, restore."""
    if not dry_run:
        control.ensure_baseline()  # capture pristine baseline ONCE (crash-safe)
    detector = profiles.Detector()
    stop = {"v": False}

    def _sig(*_a):
        stop["v"] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    try:
        while not stop["v"]:
            run_once(detector, dry_run=dry_run, memguard_on=memguard_on)
            slept = 0.0
            while slept < interval and not stop["v"]:
                time.sleep(min(0.5, interval - slept))
                slept += 0.5
    finally:
        if not dry_run:
            control.restore()
