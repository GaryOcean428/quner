"""quner — portable Linux efficiency daemon.

Tunes the operating point (CPU governor / RAPL package power / NVIDIA power-cap)
to the work-per-joule interior optimum and holds it, adapting between idle and
heavy-compute profiles. Capability-detecting and fail-loud: it tunes whatever
levers a host exposes and reports the absent ones rather than silently no-op'ing.
"""

__version__ = "0.1.1"
