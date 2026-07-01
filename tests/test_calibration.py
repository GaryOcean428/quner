from quner import calibration as k


def test_curve_peaks_at_interior():
    assert max(k.EXP132_INFO_PER_JOULE, key=k.EXP132_INFO_PER_JOULE.get) == 1.5
    assert k.EXP132_INTERIOR_OPTIMUM_H == 1.5


def test_band_constant():
    assert k.EXP132_INVARIANT_BAND_REL == 0.0191


def test_principle_mentions_interior_and_remeasured():
    p = k.principle().lower()
    assert "interior" in p and "re-measured" in p
