"""Hardware energy + operating-state telemetry.

Pure engineering plumbing: reads real energy counters and exposes the OS knobs
that move the operating point. Every path is built from ``SYSFS_ROOT()`` /
``PROC_ROOT()`` (default ``/sys`` / ``/proc``) and the ``nvidia-smi`` binary
from ``nvidia_smi()`` — all overridable by environment, so the *real* read/write
code can be exercised against a fake tree (``QUNER_SYSFS_ROOT``) or a mock GPU
(``QUNER_NVIDIA_SMI``) with zero impact on the host.

Every reader degrades to ``None``/empty on a host without the interface (VM,
no NVIDIA driver, locked-down) — the caller reports "unavailable", never a
silent success. Ported and made standalone from qig-applied efficiency
telemetry + inference accelerate (no qig_applied import).
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

__all__ = [
    "SYSFS_ROOT", "PROC_ROOT", "nvidia_smi",
    "gpu_power_limit_range_w", "read_gpu_power_w", "set_gpu_power_limit_w",
    "PowerSampler",
    "rapl_available", "read_rapl_energy_uj", "rapl_delta_j",
    "cpufreq_available", "available_governors", "current_governor", "set_governor",
    "EnergyReading", "EnergySampler", "telemetry_status",
]


# ── environment-overridable roots (read at call time, so tests can monkeypatch) ─

def SYSFS_ROOT() -> str:
    return os.environ.get("QUNER_SYSFS_ROOT", "/sys")


def PROC_ROOT() -> str:
    return os.environ.get("QUNER_PROC_ROOT", "/proc")


def nvidia_smi() -> str | None:
    """Path to nvidia-smi, or None if absent. ``QUNER_NVIDIA_SMI`` overrides
    (used only if it actually exists, so a bogus override reads as 'no GPU')."""
    override = os.environ.get("QUNER_NVIDIA_SMI")
    if override:
        return override if os.path.exists(override) else None
    return shutil.which("nvidia-smi")


# ── GPU power telemetry (vendored from qig-applied inference/accelerate) ───────

def gpu_power_limit_range_w() -> tuple[float, float] | None:
    """(min, max) enforced power-limit in watts via nvidia-smi, or None."""
    smi = nvidia_smi()
    if smi is None:
        return None
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=power.min_limit,power.max_limit",
             "--format=csv,noheader,nounits"],
            text=True, timeout=10,
        ).strip().splitlines()[0]
        lo, hi = (float(x) for x in out.split(","))
        return lo, hi
    except Exception:
        return None


def read_gpu_power_w() -> float | None:
    """Instantaneous board power draw in watts (pynvml preferred, else smi)."""
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mw = pynvml.nvmlDeviceGetPowerUsage(h)
        pynvml.nvmlShutdown()
        return mw / 1000.0
    except Exception:
        pass
    smi = nvidia_smi()
    if smi is None:
        return None
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            text=True, timeout=10,
        ).strip().splitlines()[0]
        return float(out)
    except Exception:
        return None


def set_gpu_power_limit_w(watts: float) -> bool:
    """Set the GPU power-cap (needs sudo / NVIDIA-permitted). True on success.

    Reversible: call with the max from ``gpu_power_limit_range_w`` to restore.
    ``watts`` is clamped to the GPU's enforced [min, max] before the command
    runs, so a caller value can never push the cap outside what the driver
    permits.
    """
    smi = nvidia_smi()
    if smi is None:
        return False
    rng = gpu_power_limit_range_w()
    if rng is not None:
        lo, hi = rng
        watts = max(lo, min(hi, watts))
    cap = str(int(round(watts)))
    for cmd in ([smi, "-pl", cap], ["sudo", "-n", smi, "-pl", cap]):
        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15)
            return True
        except Exception:
            continue
    return False


class PowerSampler:
    """Background GPU power sampler; integrates energy (J) over a ``with`` block."""

    def __init__(self, hz: float = 10.0):
        self.hz = hz
        self._stop = threading.Event()
        self._t: threading.Thread | None = None
        self.samples: list[tuple[float, float]] = []  # (t, watts)
        self.energy_j = 0.0
        self.mean_w = 0.0

    def _run(self):
        while not self._stop.is_set():
            w = read_gpu_power_w()
            if w is not None:
                self.samples.append((time.time(), w))
            time.sleep(1.0 / self.hz)

    def __enter__(self):
        if read_gpu_power_w() is not None:
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t is not None:
            self._t.join(timeout=2.0)
        if len(self.samples) >= 2:
            e = 0.0
            for (t0, w0), (t1, w1) in zip(self.samples, self.samples[1:]):
                e += 0.5 * (w0 + w1) * (t1 - t0)  # trapezoid
            self.energy_j = e
            self.mean_w = sum(w for _, w in self.samples) / len(self.samples)
        return False


# ── RAPL CPU energy ───────────────────────────────────────────────────────────

# Top-level package domains only: "intel-rapl:0" — NOT subzones "intel-rapl:0:0".
_RAPL_PKG_RE = re.compile(r"intel-rapl:\d+$")


def _rapl_root() -> str:
    return os.path.join(SYSFS_ROOT(), "class", "powercap")


def rapl_available() -> bool:
    return bool(_rapl_package_dirs())


def _rapl_package_dirs() -> list[str]:
    root = _rapl_root()
    if not os.path.isdir(root):
        return []
    return sorted(
        d for d in glob.glob(os.path.join(root, "intel-rapl:*"))
        if _RAPL_PKG_RE.search(os.path.basename(d))
    )


def _read_int(path: str) -> int | None:
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def read_rapl_energy_uj() -> dict[str, int]:
    """Per-package RAPL energy counters in micro-joules (monotonic, may wrap)."""
    out: dict[str, int] = {}
    for d in _rapl_package_dirs():
        v = _read_int(os.path.join(d, "energy_uj"))
        if v is not None:
            out[os.path.basename(d)] = v
    return out


def _rapl_wrap_uj() -> dict[str, int]:
    out: dict[str, int] = {}
    for d in _rapl_package_dirs():
        v = _read_int(os.path.join(d, "max_energy_range_uj"))
        if v is not None:
            out[os.path.basename(d)] = v
    return out


def rapl_delta_j(start: dict[str, int], end: dict[str, int],
                 wrap: dict[str, int] | None = None) -> float | None:
    """Total CPU-package energy in joules between two RAPL snapshots.

    Wrap-aware: counters reset to 0 at ``max_energy_range_uj``; a negative raw
    delta is corrected by adding the wrap range. If a counter wrapped but its
    wrap range is unknown, returns ``None`` (no reading) rather than a corrupted
    negative total.
    """
    if not start or not end:
        return None
    wrap = wrap or _rapl_wrap_uj()
    total_uj = 0
    for pkg, e1 in end.items():
        if pkg not in start:
            continue
        d = e1 - start[pkg]
        if d < 0:  # counter wrapped
            rng = wrap.get(pkg)
            if not rng:  # wrap metadata missing -> can't correct honestly
                return None
            d += rng
        total_uj += d
    return total_uj / 1e6


# ── CPU cpufreq governor ──────────────────────────────────────────────────────

# Defence-in-depth allowlist: the only governor names the kernel cpufreq
# subsystem ships. ``set_governor`` requires membership here AND in the host's
# live ``available_governors()`` before any sysfs write — so even a spoofed read
# or a direct call bypassing the CLI choices can never write an arbitrary string.
_KNOWN_GOVERNORS = frozenset({
    "performance", "powersave", "userspace", "ondemand",
    "conservative", "schedutil",
})


def _cpufreq_glob() -> str:
    return os.path.join(SYSFS_ROOT(), "devices", "system", "cpu", "cpu[0-9]*", "cpufreq")


def cpufreq_available() -> bool:
    return bool(glob.glob(_cpufreq_glob()))


def _cpufreq_dirs() -> list[str]:
    return sorted(glob.glob(_cpufreq_glob()))


def available_governors() -> list[str]:
    dirs = _cpufreq_dirs()
    if not dirs:
        return []
    try:
        with open(os.path.join(dirs[0], "scaling_available_governors")) as fh:
            return fh.read().split()
    except OSError:
        return []


def current_governor() -> str | None:
    dirs = _cpufreq_dirs()
    if not dirs:
        return None
    try:
        with open(os.path.join(dirs[0], "scaling_governor")) as fh:
            return fh.read().strip()
    except OSError:
        return None


def set_governor(governor: str) -> bool:
    """Set the cpufreq governor on every core (needs root). True if all wrote.

    Two independent checks (static allowlist AND live availability) before any
    sysfs write, so no unsanitised string can reach ``scaling_governor``.
    """
    dirs = _cpufreq_dirs()
    if (not dirs or governor not in _KNOWN_GOVERNORS
            or governor not in available_governors()):
        return False
    ok = True
    for d in dirs:
        try:
            with open(os.path.join(d, "scaling_governor"), "w") as fh:
                fh.write(governor)
        except OSError:
            ok = False
    return ok


# ── Combined CPU+GPU energy sampler ───────────────────────────────────────────

@dataclass
class EnergyReading:
    """Energy integrated over a profiled block."""
    wall_s: float
    cpu_j: float | None = None
    gpu_j: float | None = None
    gpu_mean_w: float | None = None
    cpu_mean_w: float | None = None
    total_j: float | None = None
    sources: list[str] = field(default_factory=list)


class EnergySampler:
    """Integrate CPU (RAPL) + GPU (NVML/smi) energy over a ``with`` block.

        with EnergySampler() as es:
            ...workload...
        es.reading.total_j  # CPU+GPU joules, or None if no telemetry
    """

    def __init__(self, gpu_hz: float = 10.0):
        self._gpu = PowerSampler(hz=gpu_hz)
        self._t0 = 0.0
        self._rapl_start: dict[str, int] = {}
        self._rapl_wrap: dict[str, int] = {}
        self.reading: EnergyReading | None = None

    def __enter__(self):
        self._t0 = time.time()
        self._rapl_start = read_rapl_energy_uj()
        self._rapl_wrap = _rapl_wrap_uj()
        self._gpu.__enter__()
        return self

    def __exit__(self, *exc):
        self._gpu.__exit__(*exc)
        wall = time.time() - self._t0
        sources: list[str] = []

        cpu_j = rapl_delta_j(self._rapl_start, read_rapl_energy_uj(), self._rapl_wrap)
        if cpu_j is not None:
            sources.append("rapl")
        gpu_j = self._gpu.energy_j or None
        gpu_w = self._gpu.mean_w or None
        if gpu_j is not None:
            sources.append("nvml/smi")

        total = None
        if cpu_j is not None or gpu_j is not None:
            total = (cpu_j or 0.0) + (gpu_j or 0.0)
        cpu_w = (cpu_j / wall) if (cpu_j is not None and wall > 0) else None

        self.reading = EnergyReading(
            wall_s=wall, cpu_j=cpu_j, gpu_j=gpu_j, gpu_mean_w=gpu_w,
            cpu_mean_w=cpu_w, total_j=total, sources=sources,
        )
        return False


def telemetry_status() -> dict:
    """One-shot snapshot of which telemetry/knobs this host exposes."""
    return {
        "rapl": rapl_available(),
        "rapl_packages": list(read_rapl_energy_uj().keys()),
        "cpufreq": cpufreq_available(),
        "governors_available": available_governors(),
        "governor_current": current_governor(),
        "gpu_power_read": read_gpu_power_w() is not None,
        "gpu_power_cap_control": gpu_power_limit_range_w() is not None,
    }
