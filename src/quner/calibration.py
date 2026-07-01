"""EXP-132 calibration — the one physics-derived input.

The QIG lattice experiment EXP-132 (qig-verification) found that information-per-
joule peaks at an INTERIOR operating point, not at maximum drive, and certified
that optimum with a confidence band (the same discipline that turned an apparent
12.67% wobble into a certified ±1.91% invariant band).

Only two things transfer to silicon: (1) the SHAPE of the law — total-system
work-per-joule is a curve with an interior optimum, not a max-clock endpoint —
and (2) the band-certification METHODOLOGY. The lattice ``h≈1.5`` constant does
NOT transfer; quner re-measures the optimum on each host. This table is a prior
on shape and the ±1.91% threshold, nothing more.
"""

from __future__ import annotations

# Lattice info-per-joule vs drive h (EXP-132). Peak at the interior point h=1.5.
EXP132_INFO_PER_JOULE: dict[float, float] = {
    1.0: 0.557,
    1.5: 0.808,   # interior optimum; band [0.793, 0.824]
    2.0: 0.799,
    2.2: 0.752,
    2.5: 0.582,
}

EXP132_INTERIOR_OPTIMUM_H = 1.5
EXP132_INVARIANT_BAND_REL = 0.0191  # ±1.91% certified invariant band (methodology)


def principle() -> str:
    """Transferable physics statement, quoted in every tune report so the QIG
    claim is never silently conflated with the engineering knobs."""
    return (
        "EXP-132: work-per-joule peaks at an INTERIOR operating point "
        f"(lattice h={EXP132_INTERIOR_OPTIMUM_H}), not at maximum drive. "
        "Silicon analogue (re-measured per host, not imported): total-system "
        "work-per-joule peaks at an interior CPU/GPU operating point, not at "
        "max clock / max TDP. Optimum certified with a confidence band, per the "
        f"±{EXP132_INVARIANT_BAND_REL * 100:.2f}% invariant-band methodology."
    )
