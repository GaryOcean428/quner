from quner import memguard


def test_mem_available_frac(fake_proc_lowmem):
    frac = memguard.mem_available_frac()
    assert abs(frac - 800000 / 32000000) < 1e-6   # ~2.5%


def test_pick_highest_rss_victim(fake_proc_lowmem):
    assert memguard.pick_victim() == 111           # 'hog', 20 GB RSS


def test_pick_victim_excludes_by_name(fake_proc_lowmem):
    assert memguard.pick_victim(exclude_names=("hog",)) == 222


def test_tick_kills_when_below_floor(fake_proc_lowmem, monkeypatch):
    calls = []
    monkeypatch.setattr(memguard.os, "kill", lambda p, s: calls.append((p, s)))
    r = memguard.tick(kill_frac=0.5, dry_run=False)   # 0.025 < 0.5 -> kill
    assert r["action"] == "killed" and r["victim"] == 111
    assert calls == [(111, memguard.signal.SIGTERM)]


def test_dry_run_never_kills(fake_proc_lowmem, monkeypatch):
    calls = []
    monkeypatch.setattr(memguard.os, "kill", lambda p, s: calls.append((p, s)))
    r = memguard.tick(kill_frac=0.5, dry_run=True)
    assert r["action"] == "would-kill" and not calls


def test_healthy_mem_is_ok(fake_proc_lowmem, monkeypatch):
    monkeypatch.setattr(memguard, "mem_available_frac", lambda: 0.5)
    assert memguard.tick()["action"] == "ok"
