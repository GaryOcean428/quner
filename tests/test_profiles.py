from quner import profiles
from quner.profiles import Detector, classify
from quner.tune import OperatingState


def test_hysteresis_requires_three_consecutive():
    d = Detector(ticks=3)
    d.update(force_class="idle")
    d.update(force_class="idle")
    assert d.current == "idle"
    d.update(force_class="training")            # 1 spike -> no switch
    assert d.current == "idle"
    d.update(force_class="training")
    d.update(force_class="training")            # 3 in a row -> switch
    assert d.current == "training"


def test_single_spike_does_not_flip():
    d = Detector(ticks=3)
    d.update(force_class="training")
    d.update(force_class="idle")                # resets the run
    d.update(force_class="training")
    assert d.current == "idle"                  # never reached 3 consecutive


def test_classify_high_gpu_is_training():
    assert classify({"gpu_util": 80.0, "load1": 0.1, "nproc": 12}) == "training"


def test_classify_high_load_no_gpu_is_training():
    assert classify({"gpu_util": None, "load1": 10.0, "nproc": 12}) == "training"


def test_classify_quiet_is_idle():
    assert classify({"gpu_util": 2.0, "load1": 0.3, "nproc": 12}) == "idle"


def test_default_state_for():
    assert profiles.default_state_for("training").cpu_governor == "performance"
    assert profiles.default_state_for("idle").cpu_governor == "powersave"


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("QUNER_STATE_DIR", str(tmp_path / "state"))
    assert profiles.cache_get("fp123", "idle") is None
    profiles.cache_put("fp123", "idle", OperatingState(cpu_governor="powersave", gpu_cap_w=30.0))
    got = profiles.cache_get("fp123", "idle")
    assert got.cpu_governor == "powersave" and got.gpu_cap_w == 30.0
