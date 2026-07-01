"""reverse-PRIME — make the iGPU drive the display so the dGPU is free for compute.

The one destructive lever, so it is fenced off:
  - **opt-in only** (never on install / never in the daemon loop),
  - **no-op with a reason** where it is meaningless (no NVIDIA driver → already
    iGPU-only),
  - **dry-run first** (prints the exact change + reboot notice + TTY recovery),
  - **reboot-gated**, with the config backed up so ``disable`` can restore it.

Mechanism: NVIDIA PRIME ``on-demand`` mode — the iGPU renders the desktop while
the dGPU stays available for CUDA (that is the point; ``intel`` mode would
disable the dGPU entirely). Requires the ``nvidia-prime`` package's
``prime-select``; without it we fail loud with instructions rather than hand-
editing Xorg blindly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from quner import control, detect

_RECOVERY = ("If the display does not come back after reboot: switch to a text "
             "console (Ctrl+Alt+F3), log in, run `quner prime disable` (or "
             "`sudo prime-select nvidia`), then `sudo reboot`.")


def _has_nvidia() -> bool:
    return detect._gpu_name() is not None


def _prime_select() -> str | None:
    return shutil.which("prime-select")


def _backup_path() -> str:
    return os.path.join(control.STATE_DIR(), "prime_backup.json")


def status() -> dict:
    gpu = detect._gpu_name()
    ps = _prime_select()
    mode = None
    if ps:
        try:
            mode = subprocess.check_output([ps, "query"], text=True, timeout=10).strip()
        except Exception:
            mode = None
    return {"nvidia": gpu is not None, "gpu": gpu,
            "prime_select": ps is not None, "mode": mode}


def enable(dry_run: bool = True) -> dict:
    """Switch to PRIME on-demand (iGPU drives display, dGPU free for compute)."""
    if not _has_nvidia():
        return {"action": "noop", "reboot_required": False,
                "reason": "no nvidia driver — already iGPU-only, reverse-PRIME is moot"}
    ps = _prime_select()
    plan = [
        "set NVIDIA PRIME mode -> on-demand (iGPU renders desktop; dGPU free for CUDA)",
        f"command: sudo {ps or 'prime-select'} on-demand",
        "reboot required for the change to take effect",
    ]
    if dry_run:
        print("# reverse-PRIME (dry-run) — nothing changed")
        for line in plan:
            print(f"  - {line}")
        print(f"  - recovery: {_RECOVERY}")
        return {"action": "dry-run", "reboot_required": True,
                "method": "prime-select on-demand" if ps else "prime-select (missing)",
                "plan": plan, "recovery": _RECOVERY}
    if ps is None:
        return {"action": "unsupported", "reboot_required": False,
                "reason": "prime-select not found — install the 'nvidia-prime' "
                          "package, then re-run `quner prime enable`"}
    previous = status().get("mode")
    os.makedirs(control.STATE_DIR(), exist_ok=True)
    with open(_backup_path(), "w") as fh:
        json.dump({"mode": previous}, fh)
    rc = subprocess.call(["sudo", "-n", ps, "on-demand"])
    if rc != 0:
        return {"action": "failed", "reboot_required": False,
                "reason": f"prime-select exited {rc}"}
    return {"action": "applied", "reboot_required": True,
            "previous_mode": previous, "recovery": _RECOVERY}


def disable(dry_run: bool = True) -> dict:
    """Restore the pre-quner PRIME mode (default nvidia)."""
    previous = "nvidia"
    try:
        with open(_backup_path()) as fh:
            previous = json.load(fh).get("mode") or "nvidia"
    except (OSError, ValueError):
        pass
    ps = _prime_select()
    if dry_run:
        print(f"# reverse-PRIME disable (dry-run): would run sudo "
              f"{ps or 'prime-select'} {previous}; reboot required")
        return {"action": "dry-run", "reboot_required": True, "target_mode": previous}
    if ps is None:
        return {"action": "unsupported", "reboot_required": False,
                "reason": "prime-select not found"}
    rc = subprocess.call(["sudo", "-n", ps, previous])
    return {"action": "restored" if rc == 0 else "failed",
            "reboot_required": rc == 0, "target_mode": previous}
