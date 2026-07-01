"""Operating-point tuner — profile work-per-joule across (governor, GPU-cap,
RAPL) states, locate the INTERIOR optimum + confidence band, optionally hold it.

Ported standalone from qig-applied efficiency/daemon.py. Deltas: the ±1.91% band
comes from ``quner.calibration``; ``OperatingState`` gains an optional
``rapl_pl1_w`` applied via ``quner.control``; telemetry is ``quner.telemetry``.

Two honestly-separate layers: (1) ENGINEERING knobs (governor, GPU-cap, RAPL) —
the kernel/driver already expose these; the tuner sweeps and holds them.
(2) QIG-NATIVE reading (EXP-132) — the SHAPE of the law (interior optimum) and
the band-certification methodology. The lattice constant is re-measured, not
imported.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from quner import control
from quner.calibration import EXP132_INVARIANT_BAND_REL, principle
from quner.telemetry import (
    EnergySampler,
    current_governor,
    gpu_power_limit_range_w,
    set_governor,
    set_gpu_power_limit_w,
    telemetry_status,
)

# Relative power draw of the governors, highest -> lowest. Decides whether a
# governor-only optimum is INTERIOR (a lower-power governor wins) vs at the
# max-power endpoint. Equal-rank governors share a power tier.
_GOVERNOR_POWER_RANK = {
    "performance": 3,
    "schedutil": 2,
    "ondemand": 2,
    "userspace": 1,
    "conservative": 1,
    "powersave": 0,
}


# ── operating states ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OperatingState:
    """A point in the (CPU governor, GPU power-cap, RAPL PL1) operating space.
    Any field ``None`` means "leave this subsystem untouched"."""
    gpu_cap_w: float | None = None
    cpu_governor: str | None = None
    rapl_pl1_w: float | None = None

    def label(self) -> str:
        parts = []
        if self.cpu_governor is not None:
            parts.append(f"cpu={self.cpu_governor}")
        if self.rapl_pl1_w is not None:
            parts.append(f"rapl={int(round(self.rapl_pl1_w))}W")
        if self.gpu_cap_w is not None:
            parts.append(f"gpu={int(round(self.gpu_cap_w))}W")
        return ",".join(parts) or "default"


def apply_state(state: OperatingState) -> dict[str, bool]:
    """Apply a state to the hardware (needs root). Returns which subsystems set."""
    applied: dict[str, bool] = {}
    if state.cpu_governor is not None:
        applied["cpu_governor"] = set_governor(state.cpu_governor)
    if state.rapl_pl1_w is not None:
        applied["rapl_pl1"] = control.set_rapl_pl1_w(state.rapl_pl1_w)
    if state.gpu_cap_w is not None:
        applied["gpu_cap"] = set_gpu_power_limit_w(state.gpu_cap_w)
    return applied


# ── workload runners ──────────────────────────────────────────────────────────

WorkFn = Callable[[], float]


def command_runner(command: str, work_units: float = 1.0,
                   timeout: float = 3600.0) -> WorkFn:
    """Build a work function from a shell command. ``work_units`` = work per
    invocation (items/tokens/frames); default 1.0 → pure energy minimisation.

    SECURITY: the workload command is the operator's own — run with
    ``shell=False`` (``shlex.split`` → argv), so no shell metacharacters are
    interpreted and there is no injection surface. It inherits exactly the
    caller's privileges; the operator is the trust boundary.
    """
    argv = shlex.split(command)

    def _run() -> float:
        try:
            subprocess.run(argv, check=True, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return float(work_units)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return 0.0

    return _run


# ── profiling ─────────────────────────────────────────────────────────────────

@dataclass
class StateSample:
    state: OperatingState
    work: float
    wall_s: float
    energy_j: float | None
    work_per_s: float
    work_per_joule: float | None
    energy_sources: list[str] = field(default_factory=list)
    applied: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "state": self.state.label(),
            "gpu_cap_w": self.state.gpu_cap_w,
            "cpu_governor": self.state.cpu_governor,
            "rapl_pl1_w": self.state.rapl_pl1_w,
            "work": self.work,
            "wall_s": self.wall_s,
            "energy_j": self.energy_j,
            "work_per_s": self.work_per_s,
            "work_per_joule": self.work_per_joule,
            "energy_sources": self.energy_sources,
            "applied": self.applied,
        }


def profile_state(run: WorkFn, state: OperatingState, reps: int = 3,
                  settle_s: float = 1.0) -> StateSample:
    """Apply a state, run the workload ``reps`` times, measure work + energy."""
    applied = apply_state(state)
    time.sleep(settle_s)  # let DVFS / power-cap settle
    total_work = 0.0
    with EnergySampler() as es:
        for _ in range(max(1, reps)):
            total_work += run()
    r = es.reading
    wall = r.wall_s if r else 0.0
    energy = r.total_j if r else None
    wps = (total_work / wall) if wall > 0 else 0.0
    wpj = (total_work / energy) if (energy and energy > 0) else None
    return StateSample(
        state=state, work=total_work, wall_s=wall, energy_j=energy,
        work_per_s=wps, work_per_joule=wpj,
        energy_sources=(r.sources if r else []), applied=applied,
    )


@dataclass
class TuneReport:
    samples: list[StateSample] = field(default_factory=list)
    objective: str = "work_per_joule"
    best_state: OperatingState | None = None
    best_value: float | None = None
    is_interior: bool | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    states_within_band: int = 0
    chosen_state: OperatingState | None = None
    applied: dict[str, bool] = field(default_factory=dict)
    principle: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "objective": self.objective,
            "samples": [s.as_dict() for s in self.samples],
            "best_state": self.best_state.label() if self.best_state else None,
            "best_value": self.best_value,
            "is_interior": self.is_interior,
            "band": [self.band_lo, self.band_hi],
            "states_within_band": self.states_within_band,
            "chosen_state": self.chosen_state.label() if self.chosen_state else None,
            "applied": self.applied,
            "principle": self.principle,
            "note": self.note,
        }


def _gpu_cap_sweep(n: int = 4) -> list[float | None]:
    rng = gpu_power_limit_range_w()
    if rng is None:
        return [None]
    lo, hi = rng
    fracs = [0.6, 0.75, 0.9, 1.0][:max(1, n)]
    return sorted({round(max(lo, hi * f)) for f in fracs})


def default_states(cpu_governors: list[str] | None = None,
                   gpu_caps_w: list[float | None] | None = None,
                   ) -> list[OperatingState]:
    """Cartesian sweep of governors × GPU caps over whatever the host exposes.
    Falls back to a single ``default`` state when neither is controllable (VM)."""
    govs: list[str | None] = list(cpu_governors) if cpu_governors else [None]
    caps: list[float | None] = (list(gpu_caps_w) if gpu_caps_w is not None
                                else _gpu_cap_sweep())
    states = [OperatingState(gpu_cap_w=c, cpu_governor=g) for g in govs for c in caps]
    return states or [OperatingState()]


def tune(run: WorkFn, states: list[OperatingState] | None = None,
         objective: str = "work_per_joule", reps: int = 3,
         apply: bool = False, restore: bool = True) -> TuneReport:
    """Profile each state, locate the interior work-per-joule optimum + band.

    objective="work_per_joule" → efficiency optimum (usually interior);
    objective="work_per_s"     → raw-throughput max (usually a power endpoint).

    With ``apply`` the chosen state is set and held; otherwise (dry run) the host
    is returned to its starting governor / uncapped GPU when ``restore``.
    """
    states = states or default_states()
    rep = TuneReport(objective=objective, principle=principle())
    start_gov = current_governor()
    gpu_rng = gpu_power_limit_range_w()

    def _restore_baseline() -> None:
        if start_gov is not None:
            set_governor(start_gov)
        if gpu_rng is not None:
            set_gpu_power_limit_w(gpu_rng[1])  # uncap

    for st in states:
        rep.samples.append(profile_state(run, st, reps=reps))

    key = (lambda s: s.work_per_joule) if objective == "work_per_joule" \
        else (lambda s: s.work_per_s)
    valid = [s for s in rep.samples if key(s) is not None and key(s) > 0]
    if not valid:
        any_work = any(s.work > 0 for s in rep.samples)
        energy_seen = any(s.energy_j is not None and s.energy_j > 0
                          for s in rep.samples)
        if not any_work:
            rep.note = ("Workload produced zero work on every state (the command "
                        "exited nonzero or timed out) — check --command; no "
                        "operating point can be chosen from a failing workload.")
        elif objective == "work_per_joule" and not energy_seen:
            rep.note = ("No work-per-joule signal (energy telemetry unavailable on "
                        "this host) — reporting throughput-only baseline.")
        else:
            rep.note = ("No positive objective signal — reporting throughput-only "
                        "baseline.")
        valid = [s for s in rep.samples if s.work_per_s > 0]
        if valid:
            best = max(valid, key=lambda s: s.work_per_s)
            rep.best_state, rep.best_value = best.state, best.work_per_s
            rep.chosen_state = best.state
        if apply and rep.chosen_state is not None:
            rep.applied = apply_state(rep.chosen_state)
        elif restore:
            _restore_baseline()
        return rep

    best = max(valid, key=key)
    rep.best_state, rep.best_value = best.state, key(best)

    # Confidence band (EXP-132 invariant-band methodology): states within ±1.91%
    # of the best are statistically indistinguishable, so the optimum is only
    # "real" if it stands out of the band.
    rep.band_lo = rep.best_value * (1 - EXP132_INVARIANT_BAND_REL)
    rep.band_hi = rep.best_value * (1 + EXP132_INVARIANT_BAND_REL)
    rep.states_within_band = sum(1 for s in valid if key(s) >= rep.band_lo)

    # Interior test on two independent axes (GPU cap, CPU governor).
    gpu_interior: bool | None = None
    capped = [s for s in valid if s.state.gpu_cap_w is not None]
    if gpu_rng is not None and capped:
        max_cap = max(s.state.gpu_cap_w for s in capped)
        gpu_interior = (best.state.gpu_cap_w is not None
                        and best.state.gpu_cap_w < max_cap)

    gov_interior: bool | None = None
    ranked = [s for s in valid if s.state.cpu_governor in _GOVERNOR_POWER_RANK]
    swept_ranks = {_GOVERNOR_POWER_RANK[s.state.cpu_governor] for s in ranked}
    if len(swept_ranks) > 1:
        max_rank = max(swept_ranks)
        best_gov = best.state.cpu_governor
        gov_interior = (best_gov in _GOVERNOR_POWER_RANK
                        and _GOVERNOR_POWER_RANK[best_gov] < max_rank)

    axes = [a for a in (gpu_interior, gov_interior) if a is not None]
    if axes:
        rep.is_interior = any(axes)

    if objective == "work_per_joule":
        # Tie-break within the band toward higher throughput — never give up
        # measurable speed for an indistinguishable efficiency gain.
        in_band = [s for s in valid if key(s) >= rep.band_lo]
        rep.chosen_state = max(in_band, key=lambda s: s.work_per_s).state
    else:
        rep.chosen_state = best.state

    if apply and rep.chosen_state is not None:
        rep.applied = apply_state(rep.chosen_state)
    elif restore:
        _restore_baseline()

    return rep


def status() -> dict:
    """Host telemetry/knob snapshot + the QIG principle (for the CLI ``status``)."""
    return {"telemetry": telemetry_status(), "principle": principle()}
