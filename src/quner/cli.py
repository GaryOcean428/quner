"""quner CLI — replaced by the full argparse surface in Task 11.

Task-0 stub: only ``--version`` is wired so the console-script entrypoint and
``python -m quner`` are exercisable end-to-end before the subcommands land.
"""

from __future__ import annotations

import sys

from quner import __version__


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--version", "-V", "version"):
        print(f"quner {__version__}")
        return 0
    print(f"quner {__version__}")
    return 0
