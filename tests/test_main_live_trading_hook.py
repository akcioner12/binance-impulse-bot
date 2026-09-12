import pytest
from unittest.mock import AsyncMock, patch

import main


@pytest.mark.asyncio
async def test_on_kline_close_calls_handle_price_tick_every_time_even_without_signal():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", return_value=None) as mock_tick:
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_tick.assert_called_once_with("BTCUSDT", 100.0)


@pytest.mark.asyncio
async def test_on_kline_close_swallows_errors_from_handle_price_tick():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", side_effect=RuntimeError("boom")):
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)  # не должно упасть


class _FakeSignal:
    def __init__(self, symbol="BTCUSDT", exchange="Binance", direction="up", level=30.0,
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
async def test_on_kline_close_spawns_autotrading_task_on_first_level_signal():
    signal = _FakeSignal(level=main.IMPULSE_START_THRESHOLD)
    with patch.object(main.tracker, "update", return_value=signal), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[]), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()  # не запускаем реально, просто гасим корутину
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_on_kline_close_does_not_spawn_autotrading_task_on_level_bump():
    signal = _FakeSignal(level=main.IMPULSE_START_THRESHOLD + 10.0, is_new_peak=True)
    with patch.object(main.tracker, "update", return_value=signal), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[]), \
         patch("main.asyncio.create_task") as mock_create_task:
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_run_autotrading_for_admin_calls_handle_new_impulse():
    with patch("main.live_trading.handle_new_impulse", new=AsyncMock(return_value=None)) as mock_handle:
        await main._run_autotrading_for_admin("BTCUSDT", "Binance", "up", 100.0, 76.0)

    mock_handle.assert_called_once()
    args = mock_handle.call_args[0]
    assert args[1] == main.ADMIN_CHAT_ID
    assert args[2] == "BTCUSDT"
    assert args[3] == "Binance"
    assert args[4] == "up"
    assert args[5] == 100.0
    assert args[6] == 76.0


@pytest.mark.asyncio
async def test_run_autotrading_for_admin_swallows_errors():
    with patch("main.live_trading.handle_new_impulse", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await main._run_autotrading_for_admin("BTCUSDT", "Binance", "up", 100.0, 76.0)  # не должно упасть
