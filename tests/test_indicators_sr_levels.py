import indicators


def _candle(high, low):
    return {"open_time": 0, "open": (high + low) / 2, "high": high, "low": low, "close": (high + low) / 2, "volume": 1.0}


def _candles_with_swing_high(peak_value: float) -> list[dict]:
    highs = [10, 11, 12, 13, peak_value, 13, 12, 11, 10, 9, 8, 9, 10]
    return [_candle(high=h, low=h - 1) for h in highs]


def test_is_near_significant_level_true_when_price_close_to_prior_swing_high():
    candles = _candles_with_swing_high(peak_value=20.0)
    # Текущая цена 20.1 — в пределах 1% от исторического хая 20.0
    assert indicators.is_near_significant_level(candles, current_price=20.1, proximity_pct=1.0, window=2) is True


def test_is_near_significant_level_false_when_price_far_from_any_level():
    candles = _candles_with_swing_high(peak_value=20.0)
    assert indicators.is_near_significant_level(candles, current_price=50.0, proximity_pct=1.0, window=2) is False


def test_is_near_significant_level_respects_proximity_threshold():
    candles = _candles_with_swing_high(peak_value=20.0)
    # 22.0 — это 10% выше уровня 20.0, вне узкого порога 1%
    assert indicators.is_near_significant_level(candles, current_price=22.0, proximity_pct=1.0, window=2) is False
    # Но входит в более широкий порог 15%
    assert indicators.is_near_significant_level(candles, current_price=22.0, proximity_pct=15.0, window=2) is True


def test_is_near_significant_level_checks_swing_lows_too():
    lows = [10, 9, 8, 7, 3.0, 7, 8, 9, 10, 11, 12, 11, 10]
    candles = [_candle(high=l + 1, low=l) for l in lows]
    assert indicators.is_near_significant_level(candles, current_price=3.02, proximity_pct=1.0, window=2) is True


def test_is_near_significant_level_false_for_empty_candles():
    assert indicators.is_near_significant_level([], current_price=100.0) is False
