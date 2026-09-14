import pytest
from unittest.mock import AsyncMock, patch

import trade_signal_ux


def setup_function():
    trade_signal_ux._awaiting_confirmation.clear()


ANALYSIS = {"classification": "reversal", "atr_15m": 1.0, "atr_1h": 2.0}
PROFILE = {"is_active": 1}


@pytest.mark.asyncio
async def test_request_confirmation_sends_message_with_two_buttons_and_symbol_in_callback_data():
    execute_fn = AsyncMock()
    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()) as mock_send, \
         patch("trade_signal_ux.asyncio.create_task"):
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=76.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[150.0, 200.0],
            execute_fn=execute_fn,
        )

    mock_send.assert_called_once()
    keyboard = mock_send.call_args[0][3]
    callback_data_values = [btn["callback_data"] for row in keyboard for btn in row]
    assert "trade_confirm:defaults:BTCUSDT" in callback_data_values
    assert "trade_confirm:manual:BTCUSDT" in callback_data_values
    assert trade_signal_ux.is_awaiting_confirmation("BTCUSDT") is True


@pytest.mark.asyncio
async def test_request_confirmation_schedules_timeout_task():
    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()), \
         patch("trade_signal_ux.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=76.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[],
            execute_fn=AsyncMock(),
        )

    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_handle_confirmation_callback_defaults_calls_execute_fn_and_clears_state():
    execute_fn = AsyncMock()
    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()), \
         patch("trade_signal_ux.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=76.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[],
            execute_fn=execute_fn,
        )

    handled = await trade_signal_ux.handle_confirmation_callback("BTCUSDT", "defaults")

    assert handled is True
    execute_fn.assert_called_once()
    args = execute_fn.call_args[0]
    assert args[1] == 111        # chat_id
    assert args[2] == "BTCUSDT"  # symbol
    assert args[3] == "Binance"  # exchange
    assert args[4] == "up"       # direction
    assert args[5] == "reversal"  # classification
    assert trade_signal_ux.is_awaiting_confirmation("BTCUSDT") is False


@pytest.mark.asyncio
async def test_handle_confirmation_callback_manual_also_executes_for_now():
    execute_fn = AsyncMock()
    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()), \
         patch("trade_signal_ux.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="ETHUSDT", exchange="Binance", direction="down",
            classification="continuation", current_price=50.0, window_start_price=60.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=56, magnet_levels=[],
            execute_fn=execute_fn,
        )

    handled = await trade_signal_ux.handle_confirmation_callback("ETHUSDT", "manual")
    assert handled is True
    execute_fn.assert_called_once()


@pytest.mark.asyncio
async def test_handle_confirmation_callback_returns_false_for_unknown_symbol():
    handled = await trade_signal_ux.handle_confirmation_callback("UNKNOWN", "defaults")
    assert handled is False


@pytest.mark.asyncio
async def test_timeout_executes_when_not_confirmed_by_button():
    execute_fn = AsyncMock()
    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()), \
         patch("trade_signal_ux.asyncio.create_task") as mock_create_task, \
         patch("trade_signal_ux.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        mock_create_task.side_effect = lambda coro: coro.close()  # реальный таймер не нужен
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=76.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[],
            execute_fn=execute_fn,
        )
        # Вызываем таймаут-корутину напрямую, не полагаясь на реальное планирование задачи
        await trade_signal_ux._auto_confirm_after_timeout("BTCUSDT")

    mock_sleep.assert_called_once_with(trade_signal_ux.CONFIRMATION_TIMEOUT_SECONDS)
    execute_fn.assert_called_once()
    assert trade_signal_ux.is_awaiting_confirmation("BTCUSDT") is False


@pytest.mark.asyncio
async def test_resolve_notifies_admin_and_clears_state_when_execute_fn_raises():
    """
    Прод-инцидент 14.09.2026: BRUSDT завис в подтверждении навсегда -- ни кнопка,
    ни 5-минутный таймаут не срабатывали, без единого сообщения в лог/юзеру.
    Похоже на необработанное исключение внутри execute_fn -- задача, созданная
    через голый asyncio.create_task() без try/except, теряет исключение молча.
    Заворачиваем execute_fn в try/except: ошибка не должна оставлять сетап
    зависшим навечно и должна быть видна и в логе, и админу в Telegram.
    """
    async def failing_execute_fn(*args):
        raise RuntimeError("boom")

    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()), \
         patch("trade_signal_ux.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=76.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[],
            execute_fn=failing_execute_fn,
        )

    with patch("trade_signal_ux.send_text", new=AsyncMock()) as mock_send:
        handled = await trade_signal_ux.handle_confirmation_callback("BTCUSDT", "defaults")

    assert handled is True
    assert trade_signal_ux.is_awaiting_confirmation("BTCUSDT") is False  # не зависает навсегда
    mock_send.assert_called_once()
    assert mock_send.call_args[0][1] == 111
    assert "BTCUSDT" in mock_send.call_args[0][2]


@pytest.mark.asyncio
async def test_button_confirmation_prevents_later_timeout_from_executing_again():
    execute_fn = AsyncMock()
    with patch("trade_signal_ux.send_text_with_keyboard", new=AsyncMock()), \
         patch("trade_signal_ux.asyncio.create_task") as mock_create_task, \
         patch("trade_signal_ux.asyncio.sleep", new=AsyncMock()):
        mock_create_task.side_effect = lambda coro: coro.close()
        await trade_signal_ux.request_confirmation(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=76.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[],
            execute_fn=execute_fn,
        )

        await trade_signal_ux.handle_confirmation_callback("BTCUSDT", "defaults")
        execute_fn.assert_called_once()

        # Таймаут "срабатывает" позже -- сетап уже разрешён, повторного вызова быть не должно
        await trade_signal_ux._auto_confirm_after_timeout("BTCUSDT")
        execute_fn.assert_called_once()  # по-прежнему один раз
