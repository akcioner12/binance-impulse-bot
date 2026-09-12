import manipulation_detector as detector


def _base_kwargs(**overrides):
    kwargs = dict(
        direction="up",
        trend_4h="up",
        relevant_divergence=False,
        is_climax=False,
        funding_rate=0.0001,
        oi_diverging=False,
        near_significant_level=False,
        vwap_deviation=1.0,
    )
    kwargs.update(overrides)
    return kwargs


def test_classify_continuation_when_trend_aligned_and_no_reversal_signals():
    result = detector.classify_impulse(**_base_kwargs())
    assert result == "continuation"


def test_classify_reversal_when_trend_against_direction():
    result = detector.classify_impulse(**_base_kwargs(trend_4h="down"))
    assert result == "reversal"


def test_classify_reversal_when_divergence_present():
    result = detector.classify_impulse(**_base_kwargs(relevant_divergence=True))
    assert result == "reversal"


def test_classify_reversal_when_climax_candle():
    result = detector.classify_impulse(**_base_kwargs(is_climax=True))
    assert result == "reversal"


def test_classify_reversal_when_funding_extreme():
    result = detector.classify_impulse(**_base_kwargs(funding_rate=0.002))
    assert result == "reversal"


def test_classify_reversal_when_oi_diverging():
    result = detector.classify_impulse(**_base_kwargs(oi_diverging=True))
    assert result == "reversal"


def test_classify_reversal_when_near_significant_level():
    result = detector.classify_impulse(**_base_kwargs(near_significant_level=True))
    assert result == "reversal"


def test_classify_reversal_when_vwap_deviation_extreme():
    result = detector.classify_impulse(**_base_kwargs(vwap_deviation=8.0))
    assert result == "reversal"


def test_classify_reversal_when_vwap_deviation_extreme_negative():
    result = detector.classify_impulse(**_base_kwargs(vwap_deviation=-8.0))
    assert result == "reversal"


def test_classify_reversal_by_default_even_with_downward_direction():
    result = detector.classify_impulse(**_base_kwargs(direction="down", trend_4h="down"))
    assert result == "continuation"

    result = detector.classify_impulse(**_base_kwargs(direction="down", trend_4h="up"))
    assert result == "reversal"
