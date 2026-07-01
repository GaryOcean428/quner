from quner.cli import main


def test_version_returns_zero(capsys):
    try:
        main(["--version"])
    except SystemExit as e:               # argparse exits 0 on --version
        assert e.code == 0
    assert "quner" in capsys.readouterr().out.lower()


def test_doctor_runs(fake_sys, capsys):
    assert main(["doctor"]) == 0
    assert "governor" in capsys.readouterr().out


def test_status_runs(fake_sys, capsys):
    assert main(["status"]) == 0
    assert "principle" in capsys.readouterr().out


def test_apply_dry_run_writes_nothing(fake_sys):
    before = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text()
    assert main(["apply", "--dry-run"]) == 0
    after = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text()
    assert before == after


def test_profile_dry_run_writes_nothing(fake_sys):
    before = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text()
    assert main(["profile", "training", "--dry-run"]) == 0
    after = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text()
    assert before == after


def test_selftest_passes_on_fake_tree(fake_sys, monkeypatch, tmp_path, capsys):
    # governor flip performance<->powersave against the fake tree, then restore
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    rc = main(["selftest"])
    out = capsys.readouterr().out
    assert "selftest" in out
    assert "governor" in out
    # governor must be back to its starting value
    assert (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip() == "powersave"
    assert rc == 0


def test_memguard_dry_run(fake_proc_lowmem, capsys):
    assert main(["memguard", "--dry-run"]) == 0


def test_retune_command_dispatches(fake_sys, monkeypatch, capsys):
    from quner import daemon
    monkeypatch.setattr(daemon, "retune", lambda profile, work_fn=None: None)
    assert main(["retune"]) == 0
    assert "retune skipped" in capsys.readouterr().out


def test_tune_no_gpu_restricts_sweep(fake_sys, monkeypatch):
    from quner import tune
    captured = {}

    def fake_tune(run, states=None, **kw):
        captured["states"] = states
        return tune.TuneReport()

    monkeypatch.setattr(tune, "tune", fake_tune)
    assert main(["tune", "--no-gpu", "--command", "true"]) == 0
    assert captured["states"] and all(s.gpu_cap_w is None for s in captured["states"])
