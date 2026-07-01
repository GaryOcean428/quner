"""systemd integration — generate + install/uninstall the units.

Three units:
  - ``quner.service``          — the root daemon (ExecStart=quner serve),
                                 restores the host on stop.
  - ``quner-retune.service``   — oneshot exploratory re-tune (quner tune --apply).
  - ``quner-retune.timer``     — fires the re-tune periodically (idle-guarded in
                                 the daemon).

Unit text is pure and testable; installation writes to ``SYSTEMD_DIR()``
(``QUNER_SYSTEMD_DIR``, default /etc/systemd/system) and calls ``systemctl``.
``--dry-run`` prints the units and the commands without touching anything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

SERVICE = "quner.service"
RETUNE_SERVICE = "quner-retune.service"
RETUNE_TIMER = "quner-retune.timer"


def SYSTEMD_DIR() -> str:
    return os.environ.get("QUNER_SYSTEMD_DIR", "/etc/systemd/system")


def _quner_bin() -> str:
    """Absolute command to invoke quner from a systemd unit."""
    found = shutil.which("quner")
    return found if found else f"{sys.executable} -m quner"


def unit_text() -> str:
    q = _quner_bin()
    return f"""\
[Unit]
Description=quner — work-per-joule efficiency daemon
After=multi-user.target

[Service]
Type=simple
User=root
ExecStart={q} serve
ExecStop={q} apply --restore
Restart=on-failure
RestartSec=5
Nice=5

# quner-managed writable dirs (created + RW even under ProtectSystem=strict)
StateDirectory=quner
RuntimeDirectory=quner

# Sandboxing — safe for a root daemon that only touches sysfs + nvidia-smi.
# NB: ProtectKernelTunables is intentionally OFF (it would block the sysfs
# governor/RAPL writes); ProtectHome is read-only (not full) so a pipx-installed
# interpreter under /home stays executable.
NoNewPrivileges=yes
ProtectHome=read-only
ProtectSystem=strict
ProtectControlGroups=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectClock=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
"""


def retune_service_text() -> str:
    q = _quner_bin()
    return f"""\
[Unit]
Description=quner — periodic exploratory re-tune
After=quner.service

[Service]
Type=oneshot
User=root
ExecStart={q} retune
"""


def timer_text(interval: str = "30min") -> str:
    return f"""\
[Unit]
Description=quner — re-tune timer

[Timer]
OnBootSec=5min
OnUnitActiveSec={interval}
Persistent=true
Unit={RETUNE_SERVICE}

[Install]
WantedBy=timers.target
"""


def _units() -> dict[str, str]:
    return {
        SERVICE: unit_text(),
        RETUNE_SERVICE: retune_service_text(),
        RETUNE_TIMER: timer_text(),
    }


def _systemctl(*args: str) -> int:
    return subprocess.call(["systemctl", *args])


def install(dry_run: bool = False, interval: str = "30min") -> list[str]:
    """Write the units and enable the daemon + timer. Returns the unit paths."""
    d = SYSTEMD_DIR()
    units = _units()
    if interval != "30min":
        units[RETUNE_TIMER] = timer_text(interval)
    paths = [os.path.join(d, name) for name in units]
    if dry_run:
        print(f"# would write to {d}:")
        for name, text in units.items():
            print(f"\n# --- {name} ---\n{text}")
        print("# would run: systemctl daemon-reload && "
              "systemctl enable --now quner.service && "
              "systemctl enable --now quner-retune.timer")
        return paths
    os.makedirs(d, exist_ok=True)
    for name, text in units.items():
        with open(os.path.join(d, name), "w") as fh:
            fh.write(text)
    from quner import control
    control.ensure_baseline()   # capture the pristine baseline NOW, before tuning
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", SERVICE)
    _systemctl("enable", "--now", RETUNE_TIMER)
    return paths


def uninstall(dry_run: bool = False) -> list[str]:
    """Stop + disable + remove the units, then restore the host baseline."""
    d = SYSTEMD_DIR()
    names = list(_units())
    if dry_run:
        print(f"# would: systemctl disable --now {SERVICE} {RETUNE_TIMER}")
        print(f"# would remove {names} from {d}; then quner apply --restore")
        return [os.path.join(d, n) for n in names]
    _systemctl("disable", "--now", SERVICE)
    _systemctl("disable", "--now", RETUNE_TIMER)
    removed = []
    for name in names:
        p = os.path.join(d, name)
        try:
            os.remove(p)
            removed.append(p)
        except OSError:
            pass
    _systemctl("daemon-reload")
    from quner import control
    control.restore()
    control.clear_rollback()   # so a later re-install captures a fresh baseline
    return removed


def verify() -> bool:
    """Lint the generated units with ``systemd-analyze verify``. True if clean."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        for name, text in _units().items():
            with open(os.path.join(tmp, name), "w") as fh:
                fh.write(text)
        try:
            r = subprocess.run(
                ["systemd-analyze", "verify", os.path.join(tmp, SERVICE)],
                capture_output=True, text=True, timeout=30,
            )
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
