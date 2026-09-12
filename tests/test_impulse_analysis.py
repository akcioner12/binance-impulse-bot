import pytest
from unittest.mock import AsyncMock, patch

import impulse_analysis


def _candle(close, volume=10.0):
    return {"open_time": 0, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}


def _make_fake_fetch_klines(candles_by_interval: dict):
    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return candles_by_interval[interval]
    return fake_fetch_klines


@pytest.mark.asyncio
async def test_analyze_impulse_continuation_when_trend_aligned_and_clean():
    # Все три ряда свечей — гладкий монотонный рост без пиков/провалов,
    # оканчивающийся рядом с current_price, чтобы не задеть VWAP/S-R пороги.
    candles_15m = [_candle(100 + i) for i in range(50)]
    candles_1h = [_candle(145.0 + i * (5.0 / 23)) for i in range(24)]
    candles_4h = [_candle(120 + i) for i in range(30)]

    fake_fetch_klines = _make_fake_fetch_klines({"15m": candles_15m, "1h": candles_1h, "4h": candles_4h})

    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[
             {"timestamp": 1, "open_interest": 1000.0},
             {"timestamp": 2, "open_interest": 1010.0},
         ])):
        result = await impulse_analysis.analyze_impulse(
            session=None, symbol="BTCUSDT", exchange="Binance", direction="up", current_price=150.0
        )

    assert result["classification"] == "continuation"
    assert result["trend_4h"] == "up"
    assert result["relevant_divergence"] is False
    assert result["is_climax"] is False
    assert result["oi_diverging"] is False


@pytest.mark.asyncio
async def test_analyze_impulse_reversal_when_trend_against_direction():
    candles_15m = [_candle(100 + i) for i in range(50)]
    candles_1h = [_candle(145.0 + i * (5.0 / 23)) for i in range(24)]
    candles_4h = [_candle(150 - i) for i in range(30)]  # нисходящий тренд на 4ч

    fake_fetch_klines = _make_fake_fetch_klines({"15m": candles_15m, "1h": candles_1h, "4h": candles_4h})

    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[
             {"timestamp": 1, "open_interest": 1000.0},
             {"timestamp": 2, "open_interest": 1010.0},
         ])):
        result = await impulse_analysis.analyze_impulse(
            session=None, symbol="BTCUSDT", exchange="Binance", direction="up", current_price=150.0
        )

    assert result["classification"] == "reversal"
    assert result["trend_4h"] == "down"


@pytest.mark.asyncio
async def test_analyze_impulse_reversal_when_funding_extreme():
    candles_15m = [_candle(100 + i) for i in range(50)]
    candles_1h = [_candle(145.0 + i * (5.0 / 23)) for i in range(24)]
    candles_4h = [_candle(120 + i) for i in range(30)]

    fake_fetch_klines = _make_fake_fetch_klines({"15m": candles_15m, "1h": candles_1h, "4h": candles_4h})

    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.002)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[
             {"timestamp": 1, "open_interest": 1000.0},
             {"timestamp": 2, "open_interest": 1010.0},
         ])):
        result = await impulse_analysis.analyze_impulse(
            session=None, symbol="BTCUSDT", exchange="Binance", direction="up", current_price=150.0
        )

    assert result["classification"] == "reversal"
    assert result["funding_rate"] == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_analyze_impulse_uses_bullish_divergence_for_down_direction():
    candles_15m = [_candle(150 - i) for i in range(50)]  # монотонное падение
    candles_1h = [_candle(100.0) for _ in range(24)]
    candles_4h = [_candle(150 - i) for i in range(30)]  # тренд вниз, совпадает с direction='down'

    fake_fetch_klines = _make_fake_fetch_klines({"15m": candles_15m, "1h": candles_1h, "4h": candles_4h})

    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[
             {"timestamp": 1, "open_interest": 1000.0},
             {"timestamp": 2, "open_interest": 1010.0},
         ])):
        result = await impulse_analysis.analyze_impulse(
            session=None, symbol="BTCUSDT", exchange="Binance", direction="down", current_price=100.0
        )

    # Монотонное падение без пиков -> дивергенции нет, тренд совпадает -> continuation
    assert result["classification"] == "continuation"
    assert result["trend_4h"] == "down"


@pytest.mark.asyncio
async def test_analyze_impulse_handles_empty_15m_candles_without_crashing():
    candles_1h = [_candle(145.0 + i * (5.0 / 23)) for i in range(24)]
    candles_4h = [_candle(120 + i) for i in range(30)]

    fake_fetch_klines = _make_fake_fetch_klines({"15m": [], "1h": candles_1h, "4h": candles_4h})

    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[])):
        result = await impulse_analysis.analyze_impulse(
            session=None, symbol="BTCUSDT", exchange="Binance", direction="up", current_price=150.0
        )

    assert result["is_climax"] is False
    assert result["relevant_divergence"] is False


@pytest.mark.asyncio
async def test_analyze_impulse_returns_atr_15m_and_atr_1h():
    candles_15m = [_candle(100 + i) for i in range(50)]
    candles_1h = [_candle(145.0 + i * (5.0 / 23)) for i in range(24)]
    candles_4h = [_candle(120 + i) for i in range(30)]

    fake_fetch_klines = _make_fake_fetch_klines({"15m": candles_15m, "1h": candles_1h, "4h": candles_4h})

    with patch("impulse_analysis.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("impulse_analysis.market_data.fetch_funding_rate", new=AsyncMock(return_value=0.0001)), \
         patch("impulse_analysis.market_data.fetch_open_interest_history", new=AsyncMock(return_value=[
             {"timestamp": 1, "open_interest": 1000.0},
             {"timestamp": 2, "open_interest": 1010.0},
         ])):
        result = await impulse_analysis.analyze_impulse(
            session=None, symbol="BTCUSDT", exchange="Binance", direction="up", current_price=150.0
        )

    # Синтетические свечи из _candle() дают постоянный True Range = 2.0 (см. indicators_atr тесты)
    assert result["atr_15m"] == pytest.approx(2.0)
    assert result["atr_1h"] is not None
