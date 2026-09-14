import pytest
from unittest.mock import AsyncMock, patch

import impulse_analysis


def _candle(close, volume=10.0):
    return {"open_time": 0, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}


def _make_candles():
    # Монотонный рост цены -> RSI(14) == 100.0 ровно (avg_loss == 0).
    # Все объёмы 10.0, кроме последней свечи (50.0) -> чистые круглые числа
    # для volume_change_pct и volume_vs_avg_ratio.
    candles = [_candle(100 + i, volume=10.0) for i in range(30)]
    candles[-1] = _candle(100 + 29, volume=50.0)
    return candles


@pytest.mark.asyncio
async def test_build_alert_indicators_returns_all_fields():
    candles = _make_candles()
    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(return_value=candles)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.00015)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[
             {"timestamp": 1, "open_interest": 1000.0},
             {"timestamp": 2, "open_interest": 1100.0},
         ])):
        result = await impulse_analysis.build_alert_indicators(session=None, exchange="Binance", symbol="BTCUSDT")

    assert result["rsi"] == pytest.approx(100.0)
    assert result["volume_change_pct"] == pytest.approx(400.0)  # (50-10)/10*100
    assert result["volume_vs_avg_ratio"] == pytest.approx(5.0)  # 50 / avg(10.0) за последние 20
    assert result["funding_rate"] == pytest.approx(0.00015)
    assert result["oi_change_pct"] == pytest.approx(10.0)  # (1100-1000)/1000*100


@pytest.mark.asyncio
async def test_build_alert_indicators_returns_none_when_no_candle_data():
    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(return_value=[])), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[])):
        result = await impulse_analysis.build_alert_indicators(session=None, exchange="Binance", symbol="BTCUSDT")

    assert result is None


@pytest.mark.asyncio
async def test_build_alert_indicators_oi_change_none_when_history_unavailable():
    candles = _make_candles()
    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(return_value=candles)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[])):
        result = await impulse_analysis.build_alert_indicators(session=None, exchange="Binance", symbol="BTCUSDT")

    assert result["oi_change_pct"] is None
    assert result["rsi"] == pytest.approx(100.0)  # остальные показатели всё равно считаются
