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


@pytest.mark.asyncio
async def test_on_kline_close_spawns_entry_notification_on_part1_filled():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", return_value=["part1_filled"]), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_on_kline_close_spawns_atr_refresh_task_on_atr_refresh_needed():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", return_value=["atr_refresh_needed"]), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_pending_setup_atr_for_admin_calls_refresh():
    with patch("main.live_trading.refresh_pending_setup_atr", new=AsyncMock()) as mock_refresh:
        await main._refresh_pending_setup_atr_for_admin("LSKUSDT")

    mock_refresh.assert_called_once()
    assert mock_refresh.call_args[0][1] == "LSKUSDT"


@pytest.mark.asyncio
async def test_refresh_pending_setup_atr_for_admin_swallows_errors():
    with patch("main.live_trading.refresh_pending_setup_atr", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await main._refresh_pending_setup_atr_for_admin("LSKUSDT")  # не должно упасть


@pytest.mark.asyncio
async def test_on_kline_close_does_not_spawn_entry_notification_for_other_events():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", return_value=["closed_stop_loss"]), \
         patch("main.asyncio.create_task") as mock_create_task:
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_notify_entry_for_admin_sends_formatted_report():
    snapshot = {
        "chat_id": 111, "direction": "short", "avg_entry_price": 1.8, "quantity": 10.0,
        "stop_loss": 1.9, "take_profits": [{"level": 1.7, "size_pct": 15}],
        "tp4_size_pct": 85, "risk_amount": 1.0,
    }
    with patch("main.live_trading.get_position_snapshot", return_value=snapshot), \
         patch("main.send_text", new=AsyncMock()) as mock_send:
        await main._notify_entry_for_admin("LSKUSDT", "Binance")

    mock_send.assert_called_once()
    assert mock_send.call_args[0][1] == 111
    assert "LSKUSDT" in mock_send.call_args[0][2]


@pytest.mark.asyncio
async def test_notify_entry_for_admin_noop_when_no_position():
    with patch("main.live_trading.get_position_snapshot", return_value=None), \
         patch("main.send_text", new=AsyncMock()) as mock_send:
        await main._notify_entry_for_admin("LSKUSDT", "Binance")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_notify_entry_for_admin_swallows_errors():
    with patch("main.live_trading.get_position_snapshot", side_effect=RuntimeError("boom")):
        await main._notify_entry_for_admin("LSKUSDT", "Binance")  # не должно упасть


@pytest.mark.asyncio
async def test_on_kline_close_dispatches_queued_lifecycle_notifications():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", return_value=["tp1_hit"]), \
         patch("main.live_trading.pop_notifications", return_value=[{"chat_id": 111, "text": "TP1 исполнен"}]), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    assert mock_create_task.call_count == 1  # только уведомление, part1/part2_filled тут нет


@pytest.mark.asyncio
async def test_send_notification_sends_text():
    with patch("main.send_text", new=AsyncMock()) as mock_send:
        await main._send_notification(111, "тест")

    mock_send.assert_called_once()
    assert mock_send.call_args[0][1] == 111
    assert mock_send.call_args[0][2] == "тест"


@pytest.mark.asyncio
async def test_send_notification_swallows_errors():
    with patch("main.send_text", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await main._send_notification(111, "тест")  # не должно упасть
