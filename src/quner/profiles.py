"""Workload profiles — detect idle vs training, with hysteresis, and cache the
tuned operating point per (host, profile).

The daemon asks: is this box idle or under heavy compute? It answers from GPU
utilisation (if a GPU is present) or sustained CPU load, and only switches
profile after several consecutive agreeing ticks (hysteresis) so a transient
spike doesn't flap the operating point. The tuned ``OperatingState`` for each
(host-fingerprint, profile) is cached under ``STATE_DIR()`` so re-tunes are rare.
"""

from __future__ import annotations

import json
import os
import subprocess

from quner import control
from quner import telemetry as t
from quner.tune import OperatingState

IDLE = "idle"
TRAINING = "training"


def _gpu_util() -> float | None:
    smi = t.nvidia_smi()
    if smi is None:
        return None
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            text=True, timeout=10,
        ).strip().splitlines()[0]
        return float(out)
    except Exception:
        return None


def sample_load() -> dict:
    """Current load signal: GPU utilisation (or None), 1-min loadavg, nproc."""
    try:
        load1 = os.getloadavg()[0]
    except (OSError, AttributeError):
        load1 = 0.0
    return {"gpu_util": _gpu_util(), "load1": load1, "nproc": os.cpu_count() or 1}


def classify(sample: dict) -> str:
    """Classify a load sample. GPU-util > 30% OR 1-min load > 0.6×nproc → training."""
    gpu = sample.get("gpu_util")
    load1 = sample.get("load1", 0.0)
    nproc = sample.get("nproc", 1)
    if (gpu is not None and gpu > 30.0) or (load1 > 0.6 * nproc):
        return TRAINING
    return IDLE


class Detector:
    """Stateful classifier with N-tick hysteresis (default 3). ``.current`` is
    the committed profile; ``.update()`` feeds one sample and returns it."""

    def __init__(self, ticks: int = 3):
        self.ticks = max(1, ticks)
        self.current = IDLE
        self._candidate: str | None = None
        self._run = 0

    def update(self, force_class: str | None = None) -> str:
        cls = force_class if force_class is not None else classify(sample_load())
        if cls == self.current:
            self._candidate, self._run = None, 0
            return self.current
        if cls == self._candidate:
            self._run += 1
        else:
            self._candidate, self._run = cls, 1
        if self._run >= self.ticks:
            self.current, self._candidate, self._run = cls, None, 0
        return self.current


def default_state_for(profile: str) -> OperatingState:
    """Conservative default operating point when nothing is cached yet."""
    if profile == TRAINING:
        return OperatingState(cpu_governor="performance")  # throughput
    return OperatingState(cpu_governor="powersave")        # quiet/cool


# ── per-host operating-point cache ────────────────────────────────────────────

def _cache_path() -> str:
    return os.path.join(control.STATE_DIR(), "cache.json")


def _load_cache() -> dict:
    try:
        with open(_cache_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def cache_get(fingerprint: str, profile: str) -> OperatingState | None:
    entry = _load_cache().get(f"{fingerprint}:{profile}")
    if not entry:
        return None
    return OperatingState(
        gpu_cap_w=entry.get("gpu_cap_w"),
        cpu_governor=entry.get("cpu_governor"),
        rapl_pl1_w=entry.get("rapl_pl1_w"),
    )


def cache_put(fingerprint: str, profile: str, state: OperatingState) -> None:
    cache = _load_cache()
    cache[f"{fingerprint}:{profile}"] = {
        "gpu_cap_w": state.gpu_cap_w,
        "cpu_governor": state.cpu_governor,
        "rapl_pl1_w": state.rapl_pl1_w,
    }
    os.makedirs(control.STATE_DIR(), exist_ok=True)
    with open(_cache_path(), "w") as fh:
        json.dump(cache, fh, indent=2)
