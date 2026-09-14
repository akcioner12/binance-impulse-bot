import pytest
from unittest.mock import AsyncMock, patch

import main


@pytest.mark.asyncio
async def test_fetch_current_symbol_lists_returns_overlap_set():
    with patch("main.get_tradable_symbols", new=AsyncMock(return_value=["BTCUSDT", "ETHUSDT", "SOLUSDT"])), \
         patch("main.get_bybit_tradable_symbols", new=AsyncMock(return_value=["ETHUSDT", "SOLUSDT", "XUSDT"])):
        binance_symbols, bybit_only, overlap = await main.fetch_current_symbol_lists()

    assert sorted(binance_symbols) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert bybit_only == ["XUSDT"]
    assert overlap == {"ETHUSDT", "SOLUSDT"}


def test_is_also_on_bybit_true_for_overlap_symbol():
    main._overlap_symbols = {"ETHUSDT"}
    assert main.is_also_on_bybit("ETHUSDT") is True
    assert main.is_also_on_bybit("BTCUSDT") is False


class _FakeSignal:
    def __init__(self, symbol="ETHUSDT", exchange="Binance", direction="up", level=30.0,
                 change_pct=31.0, window_start_price=76.0, current_price=100.0, is_new_peak=False):
        self.symbol = symbol
        self.exchange = exchange
        self.direction = direction
        self.level = level
        self.change_pct = change_pct
        self.window_start_price = window_start_price
        self.current_price = current_price
        self.is_new_peak = is_new_peak


@pytest.mark.asyncio
async def test_on_kline_close_passes_also_on_bybit_true_for_overlap_symbol():
    signal = _FakeSignal(symbol="ETHUSDT", exchange="Binance", level=main.IMPULSE_START_THRESHOLD)
    main._overlap_symbols = {"ETHUSDT"}
    with patch.object(main.tracker, "update", return_value=signal), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[111]), \
         patch("main.asyncio.create_task") as mock_create_task, \
         patch("main.impulse_analysis.build_alert_indicators", new=AsyncMock(return_value=None)), \
         patch("main.broadcast_signal", new=AsyncMock()) as mock_broadcast:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("ETHUSDT", "Binance", 100.0, 1000)

    assert mock_broadcast.call_args[0][4] is True


@pytest.mark.asyncio
async def test_on_kline_close_passes_also_on_bybit_false_for_non_overlap_symbol():
    signal = _FakeSignal(symbol="BTCUSDT", exchange="Binance", level=main.IMPULSE_START_THRESHOLD)
    main._overlap_symbols = set()
    with patch.object(main.tracker, "update", return_value=signal), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[111]), \
         patch("main.asyncio.create_task") as mock_create_task, \
         patch("main.impulse_analysis.build_alert_indicators", new=AsyncMock(return_value=None)), \
         patch("main.broadcast_signal", new=AsyncMock()) as mock_broadcast:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    assert mock_broadcast.call_args[0][4] is False


@pytest.mark.asyncio
async def test_on_kline_close_also_on_bybit_false_for_bybit_sourced_signal():
    signal = _FakeSignal(symbol="XUSDT", exchange="Bybit", level=main.IMPULSE_START_THRESHOLD)
    main._overlap_symbols = {"XUSDT"}  # гипотетически, не должно случаться, но проверяем защиту
    with patch.object(main.tracker, "update", return_value=signal), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[111]), \
         patch("main.asyncio.create_task") as mock_create_task, \
         patch("main.impulse_analysis.build_alert_indicators", new=AsyncMock(return_value=None)), \
         patch("main.broadcast_signal", new=AsyncMock()) as mock_broadcast:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("XUSDT", "Bybit", 100.0, 1000)

    assert mock_broadcast.call_args[0][4] is False
