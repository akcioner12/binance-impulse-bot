import pytest

import indicators


def _candle(high, low, close):
    return {"open_time": 0, "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


def test_atr_length_matches_input():
    candles = [_candle(high=10 + i, low=9 + i, close=9.5 + i) for i in range(20)]
    result = indicators.atr(candles, period=14)
    assert len(result) == len(candles)


def test_atr_first_period_values_are_none():
    candles = [_candle(high=10 + i, low=9 + i, close=9.5 + i) for i in range(20)]
    result = indicators.atr(candles, period=14)
    assert all(v is None for v in result[:14])
    assert result[14] is not None


def test_atr_constant_range_gives_stable_value():
    # Каждая свеча: high-low = 2.0, close всегда в середине, без гэпов между свечами
    candles = [_candle(high=11.0, low=9.0, close=10.0) for _ in range(20)]
    result = indicators.atr(candles, period=14)
    assert result[14] == pytest.approx(2.0)
    assert result[-1] == pytest.approx(2.0)


def test_atr_reacts_to_wider_ranges():
    calm = [_candle(high=10.5, low=9.5, close=10.0) for _ in range(15)]
    volatile = [_candle(high=15.0, low=5.0, close=10.0) for _ in range(10)]
    candles = calm + volatile
    result = indicators.atr(candles, period=14)
    assert result[-1] > result[14]  # ATR вырос после начала волатильного участка


def test_atr_too_short_returns_all_none():
    candles = [_candle(high=10, low=9, close=9.5) for _ in range(5)]
    result = indicators.atr(candles, period=14)
    assert all(v is None for v in result)
