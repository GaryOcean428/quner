"""Privileged operating-point levers + snapshot/rollback.

The write side of the daemon: set the CPU governor, the Intel RAPL package power
limit (PL1), and the NVIDIA power-cap — each clamped/allowlisted before any
write. Every apply can be captured by ``snapshot()`` and undone by ``restore()``,
so the daemon (and ``uninstall``) always return the host to where it started.

All writes need root; on a host without a given lever the corresponding call
returns ``False``/no-op (fail-loud is the caller's job, via ``detect``).
State (the rollback file) lives under ``STATE_DIR()`` (``QUNER_STATE_DIR``).
"""

from __future__ import annotations

import json
import os

from quner import telemetry as t

__all__ = [
    "STATE_DIR", "ROLLBACK_PATH",
    "rapl_pl1_max_w", "read_rapl_pl1_uw", "set_rapl_pl1_w",
    "snapshot", "restore",
]


def STATE_DIR() -> str:
    return os.environ.get("QUNER_STATE_DIR", "/var/lib/quner")


def ROLLBACK_PATH() -> str:
    return os.path.join(STATE_DIR(), "rollback.json")


# ── RAPL PL1 (net-new writer; telemetry only reads RAPL energy) ────────────────

def _read_int(path: str) -> int | None:
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def rapl_pl1_max_w() -> dict[str, float]:
    """Per-package PL1 ceiling in watts (from ``constraint_0_max_power_uw``)."""
    out: dict[str, float] = {}
    for d in t.rapl_package_dirs():
        mx = _read_int(os.path.join(d, "constraint_0_max_power_uw"))
        if mx and mx > 0:
            out[os.path.basename(d)] = mx / 1e6
    return out


def read_rapl_pl1_uw() -> dict[str, int]:
    """Per-package current PL1 long-term limit in micro-watts."""
    out: dict[str, int] = {}
    for d in t.rapl_package_dirs():
        v = _read_int(os.path.join(d, "constraint_0_power_limit_uw"))
        if v is not None:
            out[os.path.basename(d)] = v
    return out


def set_rapl_pl1_w(watts: float) -> bool:
    """Set RAPL PL1 on every package, each clamped to [1.0, its own max]. True
    if all packages wrote. No-op → False when RAPL is absent."""
    dirs = t.rapl_package_dirs()
    if not dirs:
        return False
    maxes = rapl_pl1_max_w()
    ok = True
    for d in dirs:
        pkg = os.path.basename(d)
        hi = maxes.get(pkg)
        w = max(1.0, min(hi, watts)) if hi else max(1.0, watts)
        try:
            with open(os.path.join(d, "constraint_0_power_limit_uw"), "w") as fh:
                fh.write(str(int(round(w * 1e6))))
        except OSError:
            ok = False
    return ok


def _write_rapl_uw(pkg_uw: dict[str, int]) -> bool:
    """Restore exact per-package PL1 micro-watt values (used by ``restore``)."""
    ok = True
    by_name = {os.path.basename(d): d for d in t.rapl_package_dirs()}
    for pkg, uw in pkg_uw.items():
        d = by_name.get(pkg)
        if d is None:
            ok = False
            continue
        try:
            with open(os.path.join(d, "constraint_0_power_limit_uw"), "w") as fh:
                fh.write(str(int(uw)))
        except OSError:
            ok = False
    return ok


# ── snapshot / restore ─────────────────────────────────────────────────────────

def snapshot(persist: bool = True) -> dict:
    """Capture current governor / RAPL PL1 / GPU uncap target. Persisted to the
    rollback file (so a later process — e.g. ``uninstall`` — can restore)."""
    rng = t.gpu_power_limit_range_w()
    snap = {
        "governor": t.current_governor(),
        "rapl_pl1_uw": read_rapl_pl1_uw(),
        "gpu_uncap_w": (rng[1] if rng else None),  # max = uncapped
    }
    if persist:
        os.makedirs(STATE_DIR(), exist_ok=True)
        with open(ROLLBACK_PATH(), "w") as fh:
            json.dump(snap, fh, indent=2)
    return snap


def restore(snap: dict | None = None) -> dict[str, bool]:
    """Return the host to a snapshot (the argument, or the persisted file)."""
    if snap is None:
        try:
            with open(ROLLBACK_PATH()) as fh:
                snap = json.load(fh)
        except (OSError, ValueError):
            return {}
    applied: dict[str, bool] = {}
    if snap.get("governor"):
        applied["governor"] = t.set_governor(snap["governor"])
    if snap.get("rapl_pl1_uw"):
        applied["rapl"] = _write_rapl_uw(snap["rapl_pl1_uw"])
    if snap.get("gpu_uncap_w") is not None:
        applied["gpu"] = t.set_gpu_power_limit_w(snap["gpu_uncap_w"])
    return applied
