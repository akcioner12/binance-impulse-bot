import pytest
from unittest.mock import patch

import main


class _FakeSignal:
    def __init__(self, symbol="LSKUSDT", exchange="Binance", direction="down", level=30.0,
                 change_pct=-31.0, window_start_price=100.0, current_price=69.0, is_new_peak=False):
        self.symbol = symbol
        self.exchange = exchange
        self.direction = direction
        self.level = level
        self.change_pct = change_pct
        self.window_start_price = window_start_price
        self.current_price = current_price
        self.is_new_peak = is_new_peak


@pytest.mark.asyncio
async def test_on_kline_close_calls_dump_tracker_update_every_tick():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch.object(main.dump_tracker, "update", return_value=None) as mock_dump_update, \
         patch("main.live_trading.handle_price_tick", return_value=None):
        await main.on_kline_close("LSKUSDT", "Binance", 1.5, 1000)

    mock_dump_update.assert_called_once_with("LSKUSDT", "Binance", 1.5, 1000)


@pytest.mark.asyncio
async def test_on_kline_close_spawns_autotrading_task_on_dump_signal():
    dump_signal = _FakeSignal(level=main.IMPULSE_START_THRESHOLD)
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch.object(main.dump_tracker, "update", return_value=dump_signal), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("LSKUSDT", "Binance", 1.5, 1000)

    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_on_kline_close_does_not_spawn_autotrading_for_dump_signal_level_bump():
    dump_signal = _FakeSignal(level=main.IMPULSE_START_THRESHOLD + 10.0, is_new_peak=True)
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch.object(main.dump_tracker, "update", return_value=dump_signal), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.asyncio.create_task") as mock_create_task:
        await main.on_kline_close("LSKUSDT", "Binance", 1.5, 1000)

    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_on_kline_close_does_not_spawn_autotrading_for_old_tracker_down_signal():
    old_signal = _FakeSignal(level=main.IMPULSE_START_THRESHOLD)
    with patch.object(main.tracker, "update", return_value=old_signal), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[]), \
         patch("main.asyncio.create_task") as mock_create_task:
        await main.on_kline_close("LSKUSDT", "Binance", 1.5, 1000)

    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_on_kline_close_still_spawns_autotrading_for_old_tracker_up_signal():
    old_signal = _FakeSignal(direction="up", level=main.IMPULSE_START_THRESHOLD)
    with patch.object(main.tracker, "update", return_value=old_signal), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[]), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("LSKUSDT", "Binance", 1.5, 1000)

    mock_create_task.assert_called_once()
