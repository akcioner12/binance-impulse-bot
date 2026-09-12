import indicators


def _candle(open_, high, low, close, volume):
    return {"open_time": 0, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def test_average_volume_excludes_last_candle_by_default():
    candles = [_candle(1, 1, 1, 1, 10.0) for _ in range(5)] + [_candle(1, 1, 1, 1, 1000.0)]
    avg = indicators.average_volume(candles, lookback=5)
    assert avg == 10.0  # последняя (climax) свеча не должна попадать в среднее


def test_average_volume_uses_lookback_window():
    candles = [_candle(1, 1, 1, 1, 100.0)] + [_candle(1, 1, 1, 1, 10.0) for _ in range(5)]
    avg = indicators.average_volume(candles, lookback=5, exclude_last=False)
    assert avg == 10.0  # старая свеча с объёмом 100 не входит в окно из последних 5


def test_average_volume_empty_list_returns_zero():
    assert indicators.average_volume([], lookback=10) == 0.0


def test_is_climax_candle_true_for_high_volume_long_upper_wick():
    # Объём в 5x выше среднего, длинный верхний фитиль (отбой от хая)
    candle = _candle(open_=10.0, high=15.0, low=9.8, close=10.2, volume=500.0)
    assert indicators.is_climax_candle(candle, avg_volume=100.0) is True


def test_is_climax_candle_false_for_normal_volume():
    candle = _candle(open_=10.0, high=15.0, low=9.8, close=10.2, volume=110.0)  # объём почти как обычно
    assert indicators.is_climax_candle(candle, avg_volume=100.0) is False


def test_is_climax_candle_false_for_high_volume_no_wick():
    # Высокий объём, но свеча без значимого фитиля (чистое направленное движение)
    candle = _candle(open_=10.0, high=15.1, low=9.9, close=15.0, volume=500.0)
    assert indicators.is_climax_candle(candle, avg_volume=100.0) is False


def test_is_climax_candle_false_when_avg_volume_zero():
    candle = _candle(open_=10.0, high=15.0, low=9.8, close=10.2, volume=500.0)
    assert indicators.is_climax_candle(candle, avg_volume=0.0) is False
