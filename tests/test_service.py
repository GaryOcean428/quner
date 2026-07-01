from quner import service


def test_unit_text_is_root_and_has_execstop():
    u = service.unit_text()
    assert "User=root" in u
    assert "ExecStop" in u
    assert "serve" in u
    assert "[Install]" in u


def test_timer_text_custom_interval():
    assert "OnUnitActiveSec=15min" in service.timer_text("15min")


def test_unit_has_sandboxing_but_not_kernel_tunables():
    u = service.unit_text()
    for directive in ("NoNewPrivileges=yes", "ProtectSystem=strict",
                      "ProtectHome=read-only", "StateDirectory=quner",
                      "RuntimeDirectory=quner"):
        assert directive in u
    # MUST stay off as an active directive — it would block sysfs governor/RAPL
    # writes (the explanatory comment naming it is fine).
    assert "ProtectKernelTunables=yes" not in u
    assert "ProtectKernelTunables=true" not in u


def test_retune_service_uses_retune_not_tune_apply():
    s = service.retune_service_text()
    assert "quner" in s and " retune" in s
    assert "tune --apply" not in s


def test_install_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    sysd = tmp_path / "sysd"
    monkeypatch.setenv("QUNER_SYSTEMD_DIR", str(sysd))
    service.install(dry_run=True)
    out = capsys.readouterr().out
    assert "would write" in out
    assert not sysd.exists() or not list(sysd.glob("*"))


def test_install_writes_units(tmp_path, monkeypatch, fake_sys):
    sysd = tmp_path / "sysd"
    monkeypatch.setenv("QUNER_SYSTEMD_DIR", str(sysd))
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))  # baseline capture
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
