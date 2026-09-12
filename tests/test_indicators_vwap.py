import pytest

import indicators


def _candle(high, low, close, volume):
    return {"open_time": 0, "open": close, "high": high, "low": low, "close": close, "volume": volume}


def test_calculate_vwap_equal_volumes_equals_average_typical_price():
    candles = [
        _candle(high=11.0, low=9.0, close=10.0, volume=100.0),  # typical price = 10.0
        _candle(high=13.0, low=11.0, close=12.0, volume=100.0),  # typical price = 12.0
    ]
    vwap = indicators.calculate_vwap(candles)
    assert vwap == 11.0


def test_calculate_vwap_weights_by_volume():
    candles = [
        _candle(high=11.0, low=9.0, close=10.0, volume=900.0),  # typical price = 10.0, доминирует
        _candle(high=21.0, low=19.0, close=20.0, volume=100.0),  # typical price = 20.0
    ]
    vwap = indicators.calculate_vwap(candles)
    assert vwap == pytest.approx(11.0)  # (10*900 + 20*100) / 1000 = 11.0


def test_calculate_vwap_empty_list_returns_zero():
    assert indicators.calculate_vwap([]) == 0.0


def test_calculate_vwap_zero_volume_returns_zero():
    candles = [_candle(high=11.0, low=9.0, close=10.0, volume=0.0)]
    assert indicators.calculate_vwap(candles) == 0.0


def test_vwap_deviation_pct_positive_when_price_above_vwap():
    candles = [_candle(high=11.0, low=9.0, close=10.0, volume=100.0)]  # VWAP = 10.0
    deviation = indicators.vwap_deviation_pct(candles, current_price=11.0)
    assert deviation == pytest.approx(10.0)  # цена на 10% выше VWAP


def test_vwap_deviation_pct_negative_when_price_below_vwap():
    candles = [_candle(high=11.0, low=9.0, close=10.0, volume=100.0)]  # VWAP = 10.0
    deviation = indicators.vwap_deviation_pct(candles, current_price=9.0)
    assert deviation == pytest.approx(-10.0)


def test_vwap_deviation_pct_zero_when_vwap_undefined():
    deviation = indicators.vwap_deviation_pct([], current_price=10.0)
    assert deviation == 0.0
