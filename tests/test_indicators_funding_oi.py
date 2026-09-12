import indicators


def test_is_funding_extreme_true_above_threshold():
    assert indicators.is_funding_extreme(0.0015, threshold=0.001) is True


def test_is_funding_extreme_true_for_negative_extreme():
    assert indicators.is_funding_extreme(-0.0015, threshold=0.001) is True


def test_is_funding_extreme_false_within_normal_range():
    assert indicators.is_funding_extreme(0.0003, threshold=0.001) is False


def test_is_funding_extreme_false_at_exact_threshold_boundary_minus_epsilon():
    assert indicators.is_funding_extreme(0.00099, threshold=0.001) is False


def test_oi_price_divergence_true_when_oi_drops_significantly():
    oi_values = [1000.0, 980.0, 950.0, 920.0]  # -8% за период
    assert indicators.oi_price_divergence(oi_values, drop_threshold_pct=-5.0) is True


def test_oi_price_divergence_false_when_oi_rises():
    oi_values = [1000.0, 1010.0, 1030.0, 1050.0]  # рост OI вместе с ценой
    assert indicators.oi_price_divergence(oi_values, drop_threshold_pct=-5.0) is False


def test_oi_price_divergence_false_when_drop_below_threshold():
    oi_values = [1000.0, 990.0, 985.0, 980.0]  # -2%, недостаточно для сигнала
    assert indicators.oi_price_divergence(oi_values, drop_threshold_pct=-5.0) is False


def test_oi_price_divergence_false_for_insufficient_data():
    assert indicators.oi_price_divergence([1000.0], drop_threshold_pct=-5.0) is False
    assert indicators.oi_price_divergence([], drop_threshold_pct=-5.0) is False


def test_oi_price_divergence_false_when_first_value_zero():
    assert indicators.oi_price_divergence([0.0, 100.0], drop_threshold_pct=-5.0) is False
