import inspect

import pytest
from unittest.mock import AsyncMock, patch, call

import main


def _candle(open_time_ms, high):
    return {"open_time": open_time_ms, "open": high, "high": high, "low": high, "close": high, "volume": 1.0}


@pytest.mark.asyncio
async def test_seed_dump_history_splits_completed_days_and_current_day():
    candles = [_candle(i * 86400_000, 100.0 + i) for i in range(9)] + [_candle(9 * 86400_000, 55.0)]

    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return candles

    with patch("main.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch.object(main.dump_tracker, "seed_history") as mock_seed:
        await main._seed_dump_history(session=None, binance_symbols=["LSKUSDT"], bybit_only=[])

    expected_highs = [100.0 + i for i in range(9)]
    mock_seed.assert_called_once_with("LSKUSDT", expected_highs, 55.0, 9 * 86400)


@pytest.mark.asyncio
async def test_seed_dump_history_seeds_binance_and_bybit_symbols():
    binance_candles = [_candle(0, 10.0), _candle(86400_000, 20.0)]
    bybit_candles = [_candle(0, 5.0), _candle(86400_000, 6.0)]

    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return binance_candles if exchange == "Binance" else bybit_candles

    with patch("main.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch.object(main.dump_tracker, "seed_history") as mock_seed:
        await main._seed_dump_history(session=None, binance_symbols=["BTCUSDT"], bybit_only=["XUSDT"])

    mock_seed.assert_has_calls([
        call("BTCUSDT", [10.0], 20.0, 86400),
        call("XUSDT", [5.0], 6.0, 86400),
    ], any_order=True)


@pytest.mark.asyncio
async def test_seed_dump_history_swallows_per_symbol_errors():
    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        if symbol == "BROKENUSDT":
            raise RuntimeError("boom")
        return [_candle(0, 10.0), _candle(86400_000, 20.0)]

    with patch("main.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch.object(main.dump_tracker, "seed_history") as mock_seed:
        await main._seed_dump_history(session=None, binance_symbols=["BROKENUSDT", "BTCUSDT"], bybit_only=[])  # не должно упасть

    mock_seed.assert_called_once_with("BTCUSDT", [10.0], 20.0, 86400)


@pytest.mark.asyncio
async def test_seed_dump_history_noop_on_empty_candles():
    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return []

    with patch("main.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch.object(main.dump_tracker, "seed_history") as mock_seed:
        await main._seed_dump_history(session=None, binance_symbols=["BTCUSDT"], bybit_only=[])

    mock_seed.assert_not_called()


def test_collectors_supervisor_source_seeds_dump_history_on_first_run():
    source = inspect.getsource(main.collectors_supervisor)
    assert "_seed_dump_history(seed_session, binance_symbols, bybit_only)" in source
