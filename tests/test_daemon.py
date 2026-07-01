import json
import os

from quner import daemon
from quner.profiles import Detector


def test_retune_refuses_during_training():
    # never sweep power while a run is active (coordination seam #4)
    assert daemon.retune("training") is None


def test_run_once_writes_status(fake_sys, tmp_path, monkeypatch):
    monkeypatch.setenv("QUNER_RUN_DIR", str(tmp_path / "run"))
    st = daemon.run_once(Detector(ticks=1), dry_run=True)
    assert st["profile"] in ("idle", "training")
    assert st["dry_run"] is True
    assert st["applied"] == {}                      # dry-run applies nothing
    written = json.load(open(os.path.join(str(tmp_path / "run"), "status.json")))
    assert written["profile"] == st["profile"]
    assert "capabilities" in written


def test_run_once_dry_run_does_not_change_real_governor(fake_sys, tmp_path, monkeypatch):
    monkeypatch.setenv("QUNER_RUN_DIR", str(tmp_path / "run"))
    before = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text()
    daemon.run_once(Detector(ticks=1), dry_run=True)
    after = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text()
    assert before == after
