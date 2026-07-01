from quner import telemetry as t


def test_governors_from_fake_tree(fake_sys):
    assert t.available_governors() == ["performance", "powersave"]
    assert t.current_governor() == "powersave"
    assert t.cpufreq_available() is True


def test_set_governor_allowlist_rejects_unknown(fake_sys):
    assert t.set_governor("evil; rm -rf") is False
    gov = (fake_sys / "devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    assert gov == "powersave"


def test_set_governor_rejects_known_but_unavailable(fake_sys):
    # schedutil is in the allowlist but NOT offered by this fake host
    assert t.set_governor("schedutil") is False


def test_set_governor_writes_all_cores(fake_sys):
    assert t.set_governor("performance") is True
    for c in (0, 1):
        gov = (fake_sys / f"devices/system/cpu/cpu{c}/cpufreq/scaling_governor").read_text().strip()
        assert gov == "performance"


def test_rapl_available_and_read(fake_sys):
    assert t.rapl_available() is True
    assert t.read_rapl_energy_uj() == {"intel-rapl:0": 1000000}


def test_rapl_wrap_correction():
    # counter wrapped (5 < 10): corrected delta = (5 - 10 + 100) = 95 uJ
    assert t.rapl_delta_j({"intel-rapl:0": 10}, {"intel-rapl:0": 5},
                          {"intel-rapl:0": 100}) == 95 / 1e6


def test_rapl_wrap_unknown_returns_none():
    # non-empty wrap dict missing this package -> can't correct honestly -> None
    # (an empty dict is falsy and triggers the documented sysfs auto-detect)
    assert t.rapl_delta_j({"intel-rapl:0": 10}, {"intel-rapl:0": 5},
                          {"intel-rapl:1": 100}) is None


def test_gpu_unavailable_when_no_smi(fake_sys):
    # fake_sys points QUNER_NVIDIA_SMI at a nonexistent path
    assert t.nvidia_smi() is None
    assert t.gpu_power_limit_range_w() is None
    assert t.set_gpu_power_limit_w(30) is False


def test_telemetry_status_shape(fake_sys):
    s = t.telemetry_status()
    assert s["cpufreq"] is True
    assert s["governors_available"] == ["performance", "powersave"]
    assert s["gpu_power_cap_control"] is False
