import subprocess
import sys


def test_version_importable():
    import quner

    assert quner.__version__


def test_cli_entrypoint_runs():
    r = subprocess.run(
        [sys.executable, "-m", "quner", "--version"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "quner" in r.stdout.lower()
