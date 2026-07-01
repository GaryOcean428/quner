from quner import prime


def test_enable_noop_without_nvidia(monkeypatch):
    monkeypatch.setenv("QUNER_NVIDIA_SMI", "/nonexistent")
    r = prime.enable(dry_run=True)
    assert r["action"] == "noop"
    assert "no nvidia" in r["reason"].lower()
    assert r["reboot_required"] is False


def test_enable_dry_run_is_reboot_gated(fake_nvidia, capsys):
    r = prime.enable(dry_run=True)
    assert r["action"] == "dry-run"
    assert r["reboot_required"] is True
    assert "recovery" in r
    out = capsys.readouterr().out
    assert "dry-run" in out and "reboot" in out.lower()


def test_status_reports_nvidia_presence(fake_nvidia):
    s = prime.status()
    assert s["nvidia"] is True
    assert "1650" in (s["gpu"] or "")


def test_disable_dry_run(fake_nvidia, tmp_path, monkeypatch):
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    r = prime.disable(dry_run=True)
    assert r["action"] == "dry-run" and r["reboot_required"] is True
