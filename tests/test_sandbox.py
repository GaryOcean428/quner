"""The release sandbox must stop at a failed gate, before invoking hardware tooling."""
import subprocess
from pathlib import Path


def test_sandbox_stops_when_unit_tests_fail(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    source = Path(__file__).resolve().parents[1] / "sandbox" / "run_sandbox.sh"
    script = sandbox / "run_sandbox.sh"
    script.write_text(source.read_text())
    for name in ("make_fake_sys.sh", "mock-nvidia-smi"):
        (sandbox / name).write_text("#!/bin/bash\nexit 0\n")
    bindir = tmp_path / ".venv" / "bin"
    bindir.mkdir(parents=True)
    for name, code in (("python", 42), ("quner", 99)):
        tool = bindir / name
        tool.write_text(f"#!/bin/bash\nexit {code}\n")
        tool.chmod(0o755)
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert result.returncode == 42, result.stdout + result.stderr
    assert "LAYER-A GREEN" not in result.stdout
