import indicators


def _candles_from_closes(closes: list[float]) -> list[dict]:
    return [{"open": c, "high": c, "low": c, "close": c, "volume": 1.0, "open_time": i} for i, c in enumerate(closes)]


def test_ema_empty_list_returns_empty():
    assert indicators.ema([], 10) == []


def test_ema_first_value_equals_input():
    result = indicators.ema([10.0, 20.0, 30.0], period=5)
    assert result[0] == 10.0


def test_ema_length_matches_input():
    values = [float(i) for i in range(30)]
    result = indicators.ema(values, period=10)
    assert len(result) == len(values)


def test_ema_smooths_toward_rising_prices():
    values = [10.0] * 10 + [20.0] * 10
    result = indicators.ema(values, period=5)
    # После продолжительного роста EMA должна быть заметно выше стартового значения
    assert result[-1] > 15.0
    assert result[-1] < 20.0


def test_trend_direction_up_for_rising_closes():
    closes = [float(i) for i in range(1, 31)]  # монотонный рост
    candles = _candles_from_closes(closes)
    assert indicators.trend_direction(candles, period=20) == "up"


def test_trend_direction_down_for_falling_closes():
    closes = [float(30 - i) for i in range(30)]  # монотонное падение
    candles = _candles_from_closes(closes)
    assert indicators.trend_direction(candles, period=20) == "down"


def test_trend_direction_flat_for_sideways_closes():
    closes = [10.0, 10.1, 9.9, 10.05, 9.95] * 6
    candles = _candles_from_closes(closes)
    assert indicators.trend_direction(candles, period=20) == "flat"


def test_trend_direction_flat_when_not_enough_candles():
    candles = _candles_from_closes([10.0, 11.0, 12.0])
    assert indicators.trend_direction(candles, period=20) == "flat"
