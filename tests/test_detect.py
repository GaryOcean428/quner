from quner import detect


def test_leverless_tree_reports_unavailable(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("QUNER_SYSFS_ROOT", str(empty))
    monkeypatch.setenv("QUNER_NVIDIA_SMI", "/nonexistent")
    caps = detect.capabilities()
    assert caps["governor"]["available"] is False
    assert caps["rapl"]["available"] is False
    assert caps["gpu_cap"]["available"] is False
    assert caps["display_prime"]["available"] is False
    assert any("unavailable" in line for line in detect.doctor_lines())


def test_fake_tree_governor_and_rapl_available(fake_sys):
    caps = detect.capabilities()
    assert caps["governor"]["available"] is True
    assert caps["rapl"]["available"] is True
    assert caps["gpu_cap"]["available"] is False        # QUNER_NVIDIA_SMI bogus
    assert "performance" in caps["governor"]["detail"]


def test_fingerprint_stable_and_short(fake_sys):
    fp1 = detect.host_fingerprint()
    fp2 = detect.host_fingerprint()
    assert fp1 == fp2 and len(fp1) == 16
