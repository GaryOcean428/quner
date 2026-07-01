from quner import service


def test_unit_text_is_root_and_has_execstop():
    u = service.unit_text()
    assert "User=root" in u
    assert "ExecStop" in u
    assert "serve" in u
    assert "[Install]" in u


def test_timer_text_custom_interval():
    assert "OnUnitActiveSec=15min" in service.timer_text("15min")


def test_install_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    sysd = tmp_path / "sysd"
    monkeypatch.setenv("QUNER_SYSTEMD_DIR", str(sysd))
    service.install(dry_run=True)
    out = capsys.readouterr().out
    assert "would write" in out
    assert not sysd.exists() or not list(sysd.glob("*"))


def test_install_writes_units(tmp_path, monkeypatch):
    sysd = tmp_path / "sysd"
    monkeypatch.setenv("QUNER_SYSTEMD_DIR", str(sysd))
    monkeypatch.setattr(service, "_systemctl", lambda *a: 0)
    paths = service.install(dry_run=False)
    assert (sysd / "quner.service").exists()
    assert (sysd / "quner-retune.timer").exists()
    assert any(p.endswith("quner.service") for p in paths)


def test_uninstall_removes_units(tmp_path, monkeypatch):
    sysd = tmp_path / "sysd"
    monkeypatch.setenv("QUNER_SYSTEMD_DIR", str(sysd))
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(service, "_systemctl", lambda *a: 0)
    service.install(dry_run=False)
    service.uninstall(dry_run=False)
    assert not (sysd / "quner.service").exists()
