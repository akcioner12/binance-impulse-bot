import pytest
from unittest.mock import AsyncMock, patch, call

import main


def _candle(open_time_ms, close):
    return {"open_time": open_time_ms, "open": close, "high": close, "low": close, "close": close, "volume": 1.0}


@pytest.mark.asyncio
async def test_seed_price_history_seeds_binance_and_bybit_symbols():
    binance_candles = [_candle(1000_000, 100.0), _candle(1003600_000, 105.0)]
    bybit_candles = [_candle(2000_000, 50.0)]

    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return binance_candles if exchange == "Binance" else bybit_candles

    with patch("main.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch.object(main.tracker, "seed_history") as mock_seed:
        await main._seed_price_history(session=None, binance_symbols=["BTCUSDT"], bybit_only=["XUSDT"])

    mock_seed.assert_has_calls([
        call("BTCUSDT", [(1000, 100.0), (1003600, 105.0)]),
        call("XUSDT", [(2000, 50.0)]),
    ], any_order=True)


@pytest.mark.asyncio
async def test_seed_price_history_swallows_per_symbol_errors():
    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        if symbol == "BROKENUSDT":
            raise RuntimeError("boom")
        return [_candle(1000_000, 100.0)]

    with patch("main.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch.object(main.tracker, "seed_history") as mock_seed:
        await main._seed_price_history(session=None, binance_symbols=["BROKENUSDT", "BTCUSDT"], bybit_only=[])  # не должно упасть

    mock_seed.assert_called_once_with("BTCUSDT", [(1000, 100.0)])
