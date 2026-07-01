"""memguard — OOM watchdog.

A runaway training run can exhaust RAM and hard-lock the box before the kernel
OOM killer reacts. memguard watches ``MemAvailable`` and, below a hard floor,
SIGTERMs the single largest-RSS non-critical process — never PID 1, never
quner itself, never sshd/systemd — so you keep an interactive session.

Reads ``/proc`` via ``PROC_ROOT()`` so it is testable against a fake tree.
Disabled by default; the daemon enables it by config.
"""

from __future__ import annotations

import os
import signal

from quner.telemetry import PROC_ROOT

# Never target these — losing them costs you the session or the box.
CRITICAL_NAMES = frozenset({
    "systemd", "init", "sshd", "sudo", "dbus-daemon", "quner", "login",
    "bash", "zsh", "fish", "sh", "dash", "systemd-logind",
})


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open(os.path.join(PROC_ROOT(), "meminfo")) as fh:
            for line in fh:
                k, _, rest = line.partition(":")
                out[k.strip()] = int(rest.strip().split()[0])  # kB
    except (OSError, ValueError, IndexError):
        pass
    return out


def mem_available_frac() -> float:
    """MemAvailable / MemTotal (1.0 if meminfo unreadable — fail safe, no kill)."""
    mi = _meminfo()
    total = mi.get("MemTotal")
    avail = mi.get("MemAvailable")
    if not total or avail is None:
        return 1.0
    return avail / total


def _iter_pids() -> list[int]:
    try:
        return [int(n) for n in os.listdir(PROC_ROOT()) if n.isdigit()]
    except OSError:
        return []


def _comm(pid: int) -> str:
    try:
        with open(os.path.join(PROC_ROOT(), str(pid), "comm")) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _rss_kb(pid: int) -> int | None:
    try:
        with open(os.path.join(PROC_ROOT(), str(pid), "status")) as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def pick_victim(exclude_pids: tuple[int, ...] = (),
                exclude_names: tuple[str, ...] = ()) -> int | None:
    """Highest-RSS process, excluding PID 1, quner's own PID, and critical names."""
    excl_names = CRITICAL_NAMES | set(exclude_names)
    best: int | None = None
    best_rss = -1
    for pid in _iter_pids():
        if pid == 1 or pid == os.getpid() or pid in exclude_pids:
            continue
        if _comm(pid) in excl_names:
            continue
        rss = _rss_kb(pid)
        if rss is not None and rss > best_rss:
            best_rss, best = rss, pid
    return best


def tick(warn_frac: float = 0.08, kill_frac: float = 0.04, dry_run: bool = False,
         exclude_pids: tuple[int, ...] = (),
         exclude_names: tuple[str, ...] = ()) -> dict:
    """One watchdog tick. Returns the action taken.

    action ∈ {ok, warn, no-victim, would-kill, killed, kill-failed}.
    """
    frac = mem_available_frac()
    if frac > warn_frac:
        return {"action": "ok", "mem_available_frac": frac}
    if frac > kill_frac:
        return {"action": "warn", "mem_available_frac": frac}
    victim = pick_victim(exclude_pids, exclude_names)
    if victim is None:
        return {"action": "no-victim", "mem_available_frac": frac}
    if dry_run:
        return {"action": "would-kill", "victim": victim, "victim_name": _comm(victim),
                "mem_available_frac": frac}
    try:
        os.kill(victim, signal.SIGTERM)
    except OSError:
        return {"action": "kill-failed", "victim": victim, "mem_available_frac": frac}
    return {"action": "killed", "victim": victim, "victim_name": _comm(victim),
            "mem_available_frac": frac}
