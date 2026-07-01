import os

import pytest


@pytest.fixture
def fake_sys(tmp_path, monkeypatch):
    """A fake /sys tree: 2 cpufreq cores + one intel-rapl package."""
    root = tmp_path / "sys"
    for c in (0, 1):
        d = root / f"devices/system/cpu/cpu{c}/cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_available_governors").write_text("performance powersave\n")
        (d / "scaling_governor").write_text("powersave\n")
    rp = root / "class/powercap/intel-rapl:0"
    rp.mkdir(parents=True)
    (rp / "energy_uj").write_text("1000000\n")
    (rp / "max_energy_range_uj").write_text("262143328850\n")
    (rp / "constraint_0_name").write_text("long_term\n")
    (rp / "constraint_0_power_limit_uw").write_text("85000000\n")
    (rp / "constraint_0_max_power_uw").write_text("45000000\n")
    monkeypatch.setenv("QUNER_SYSFS_ROOT", str(root))
    monkeypatch.setenv("QUNER_NVIDIA_SMI", "/nonexistent/nvidia-smi")
    return root


@pytest.fixture
def fake_nvidia(tmp_path, monkeypatch):
    """A mock nvidia-smi so a host reads as 'NVIDIA present'."""
    smi = tmp_path / "nvidia-smi"
    smi.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        "  *name*) echo 'NVIDIA GeForce GTX 1650 Ti' ;;\n"
        "  *min_limit*) echo '1.00, 50.00' ;;\n"
        "  *power.draw*) echo '5.0' ;;\n"
        "  *utilization*) echo '10' ;;\n"
        "  *-pl*) exit 0 ;;\n"
        "  *) echo '' ;;\n"
        "esac\n"
    )
    smi.chmod(0o755)
    monkeypatch.setenv("QUNER_NVIDIA_SMI", str(smi))
    return smi


@pytest.fixture
def fake_proc_lowmem(tmp_path, monkeypatch):
    """A fake /proc with low MemAvailable and two RSS-bearing processes."""
    root = tmp_path / "proc"
    root.mkdir()
    (root / "meminfo").write_text(
        "MemTotal:       32000000 kB\n"
        "MemFree:          500000 kB\n"
        "MemAvailable:     800000 kB\n"  # ~2.5% available
    )
    procs = {111: ("hog", 20_000_000), 222: ("small", 1_000_000)}
    for pid, (comm, rss_kb) in procs.items():
        d = root / str(pid)
        d.mkdir()
        (d / "comm").write_text(comm + "\n")
        (d / "status").write_text(
            f"Name:\t{comm}\nPid:\t{pid}\nVmRSS:\t{rss_kb} kB\n"
        )
    monkeypatch.setenv("QUNER_PROC_ROOT", str(root))
    return root
