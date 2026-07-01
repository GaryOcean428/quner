"""Capability detection — the ``doctor`` report + host fingerprint.

quner tunes whatever levers a host exposes and reports the absent ones. This
module turns the raw telemetry probes into a structured capability map and
human-readable lines, and computes a stable host fingerprint used to key the
per-host operating-point cache.

fail-loud: an absent lever is reported as ``available: False`` with a reason,
never silently omitted.
"""

from __future__ import annotations

import hashlib
import os

from quner import telemetry as t


def _cpu_model() -> str:
    path = os.path.join(t.PROC_ROOT(), "cpuinfo")
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown-cpu"


def _gpu_name() -> str | None:
    smi = t.nvidia_smi()
    if smi is None:
        return None
    import subprocess
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=name", "--format=csv,noheader"],
            text=True, timeout=10,
        ).strip().splitlines()
        return out[0] if out else None
    except Exception:
        return None


def capabilities() -> dict:
    """Per-lever ``{available, detail}`` map for governor / rapl / gpu_cap /
    display_prime."""
    govs = t.available_governors()
    gpu_rng = t.gpu_power_limit_range_w()
    gpu_name = _gpu_name()
    rapl_pkgs = list(t.read_rapl_energy_uj().keys())

    return {
        "governor": {
            "available": t.cpufreq_available(),
            "detail": (f"governors: {', '.join(govs)}; current: {t.current_governor()}"
                       if govs else "no cpufreq (VM or unsupported)"),
        },
        "rapl": {
            "available": t.rapl_available(),
            "detail": (f"packages: {', '.join(rapl_pkgs)}" if rapl_pkgs
                       else ("intel-rapl present; energy counter is root-only "
                             "(full readout under the daemon/root)"
                             if t.rapl_available()
                             else "no intel-rapl powercap (not exposed here)")),
        },
        "gpu_cap": {
            "available": gpu_rng is not None,
            "detail": (f"{gpu_name}: cap {gpu_rng[0]:.0f}-{gpu_rng[1]:.0f}W"
                       if gpu_rng else
                       ("nvidia-smi present but power-cap not settable"
                        if gpu_name else "no nvidia-smi (driver not installed)")),
        },
        "display_prime": {
            "available": gpu_name is not None,
            "detail": ("reverse-PRIME possible (dGPU present)" if gpu_name
                       else "no dGPU driver — already iGPU-only, PRIME is moot"),
        },
    }


def doctor_lines() -> list[str]:
    """Human-readable capability lines (the ``quner doctor`` body)."""
    caps = capabilities()
    label = {
        "governor": "cpu governor",
        "rapl": "rapl pkg power",
        "gpu_cap": "nvidia -pl",
        "display_prime": "reverse-PRIME",
    }
    lines = []
    for key, name in label.items():
        c = caps[key]
        mark = "available" if c["available"] else "unavailable"
        lines.append(f"{name:>15}: {mark} — {c['detail']}")
    return lines


def host_fingerprint() -> str:
    """Stable short hash of CPU model + governors + GPU name (cache key)."""
    parts = [_cpu_model(), ",".join(t.available_governors()), _gpu_name() or "no-gpu"]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
