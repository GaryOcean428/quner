from quner import control as c
from quner import telemetry as t


def test_rapl_clamp_and_write(fake_sys, monkeypatch, tmp_path):
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    # request 1000W; fake host max is 45W -> clamped
    assert c.set_rapl_pl1_w(1000) is True
    v = int((fake_sys / "class/powercap/intel-rapl:0/constraint_0_power_limit_uw").read_text())
    assert v == 45_000_000


def test_rapl_absent_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("QUNER_SYSFS_ROOT", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    assert c.set_rapl_pl1_w(30) is False


def test_snapshot_restore_roundtrip(fake_sys, monkeypatch, tmp_path):
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    snap = c.snapshot()
    assert snap["governor"] == "powersave"
    assert snap["rapl_pl1_uw"] == {"intel-rapl:0": 85_000_000}
    # perturb, then restore from the persisted file
    t.set_governor("performance")
    c.set_rapl_pl1_w(20)
    assert t.current_governor() == "performance"
    c.restore()
    assert t.current_governor() == "powersave"
    v = int((fake_sys / "class/powercap/intel-rapl:0/constraint_0_power_limit_uw").read_text())
    assert v == 85_000_000


def test_restore_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "nostate"))
    assert c.restore() == {}


def test_ensure_baseline_captures_once(fake_sys, monkeypatch, tmp_path):
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    b1 = c.ensure_baseline()
    assert b1["governor"] == "powersave"
    # perturb, then ensure_baseline again -> must return the ORIGINAL (crash-safe)
    t.set_governor("performance")
    b2 = c.ensure_baseline()
    assert b2["governor"] == "powersave"        # preserved, not re-snapshotted
    # after clear, it re-captures the (now perturbed) state
    c.clear_rollback()
    b3 = c.ensure_baseline()
    assert b3["governor"] == "performance"
