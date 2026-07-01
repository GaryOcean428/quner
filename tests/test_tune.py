from quner import tune as tn
from quner.tune import OperatingState, StateSample


def _canned(state, wpj, wps):
    return StateSample(state=state, work=1.0, wall_s=1.0, energy_j=1.0,
                       work_per_s=wps, work_per_joule=wpj, energy_sources=["rapl"])


def test_interior_optimum_detected(fake_sys, monkeypatch):
    # powersave wins on work/joule; performance is the max-power endpoint
    def fake_profile(run, state, reps=3, settle_s=1.0):
        if state.cpu_governor == "powersave":
            return _canned(state, wpj=1.2, wps=5.0)
        return _canned(state, wpj=1.0, wps=8.0)

    monkeypatch.setattr(tn, "profile_state", fake_profile)
    rep = tn.tune(lambda: 1.0,
                  states=[OperatingState(cpu_governor="performance"),
                          OperatingState(cpu_governor="powersave")],
                  apply=False)
    assert rep.best_state.cpu_governor == "powersave"
    assert rep.best_value == 1.2
    assert rep.is_interior is True                     # powersave < performance tier
    assert rep.chosen_state.cpu_governor == "powersave"
    assert rep.band_lo < 1.2 <= rep.band_hi


def test_throughput_objective_picks_endpoint(fake_sys, monkeypatch):
    def fake_profile(run, state, reps=3, settle_s=1.0):
        if state.cpu_governor == "powersave":
            return _canned(state, wpj=1.2, wps=5.0)
        return _canned(state, wpj=1.0, wps=8.0)

    monkeypatch.setattr(tn, "profile_state", fake_profile)
    rep = tn.tune(lambda: 1.0,
                  states=[OperatingState(cpu_governor="performance"),
                          OperatingState(cpu_governor="powersave")],
                  objective="work_per_s", apply=False)
    assert rep.best_state.cpu_governor == "performance"  # highest throughput


def test_zero_work_reports_honest_note(fake_sys, monkeypatch):
    def fake_profile(run, state, reps=3, settle_s=1.0):
        return StateSample(state=state, work=0.0, wall_s=1.0, energy_j=1.0,
                           work_per_s=0.0, work_per_joule=None)

    monkeypatch.setattr(tn, "profile_state", fake_profile)
    rep = tn.tune(lambda: 0.0, states=[OperatingState(cpu_governor="powersave")],
                  apply=False)
    assert "zero work" in rep.note.lower()
